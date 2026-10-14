import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import connect_agent
import memory_store


class Workflows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-memory-kit-test-')
        self.base = Path(self.temp.name).resolve()
        self.vault = self.base / 'memory'
        self.pointer = self.base / 'config/path'
        self.assertEqual(self.run_script('init_vault.py', '--path', str(self.vault)).returncode, 0)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name, *args):
        code = (
            'import runpy,sys; from pathlib import Path; '
            f'sys.path.insert(0,{str(ROOT / "scripts")!r}); import common; '
            f'common.POINTER=Path({str(self.pointer)!r}); '
            f'sys.argv={[name, *args]!r}; '
            f'runpy.run_path({str(ROOT / "scripts" / name)!r},run_name="__main__")'
        )
        return subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True)

    def connect(self, entry, skills, *extra):
        return self.run_script('connect_agent.py', '--vault', str(self.vault), '--entry', str(entry), '--skills-dir', str(skills), *extra)

    def record(self, kind='preference', **fields):
        defaults = dict(summary='周报使用自然段', key='周报格式', scope='global', agent='测试Agent', source='用户明确确认')
        defaults.update(fields)
        args = ['--vault', str(self.vault), '--kind', kind]
        for key, value in defaults.items():
            args.extend(['--' + key.replace('_', '-'), value])
        result = self.run_script('record_memory.py', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['record_id']

    def apply(self, record, *extra):
        return self.run_script('apply_memory.py', '--vault', str(self.vault), '--record', record, *extra)

    def test_init_preserves_existing_data(self):
        sentinel = self.vault / 'keep.txt'
        sentinel.write_text('保留')
        before = self.pointer.read_bytes()
        result = self.run_script('init_vault.py', '--path', str(self.vault))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), '保留')
        self.assertEqual(self.pointer.read_bytes(), before)

    def test_init_dry_run_does_not_create_folder(self):
        target = self.base / 'other-memory'
        result = self.run_script('init_vault.py', '--path', str(target), '--dry-run')
        self.assertEqual(result.returncode, 0)
        self.assertFalse(target.exists())

    def test_two_agents_share_same_vault_and_preserve_rules(self):
        for name in ('a', 'b'):
            entry = self.base / (name + '.md')
            entry.write_text('我的原有规则\n')
            skills = self.base / name / 'skills'
            self.assertEqual(self.connect(entry, skills).returncode, 0)
            self.assertTrue(entry.read_text().startswith('我的原有规则\n'))
            self.assertEqual((skills / 'ai-memory-kit').resolve(), self.vault / '.kit/ai-memory-kit')

    def test_connect_is_idempotent(self):
        entry, skills = self.base / 'entry.md', self.base / 'skills'
        self.assertEqual(self.connect(entry, skills).returncode, 0)
        before = entry.read_bytes()
        self.assertEqual(self.connect(entry, skills).returncode, 0)
        self.assertEqual(entry.read_bytes(), before)

    def test_preview_does_not_write_or_disclose_old_rules(self):
        entry, skills = self.base / 'entry.md', self.base / 'skills'
        entry.write_text('PRIVATE_RULE_NOT_FOR_PREVIEW\n')
        result = self.connect(entry, skills, '--dry-run')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('PRIVATE_RULE_NOT_FOR_PREVIEW', result.stdout)
        self.assertEqual(entry.read_text(), 'PRIVATE_RULE_NOT_FOR_PREVIEW\n')
        self.assertFalse(skills.exists())

    def test_bootstrap_migration_keeps_backup(self):
        skills = self.base / 'tool/skills'
        bootstrap = skills / 'ai-memory-kit'
        shutil.copytree(ROOT, bootstrap, ignore=shutil.ignore_patterns('__pycache__', '.git'))
        (bootstrap / 'user-note.txt').write_text('我的补充')
        entry = self.base / 'tool/entry.md'
        self.assertEqual(self.connect(entry, skills, '--adopt-bootstrap', '--dry-run').returncode, 0)
        self.assertTrue(bootstrap.is_dir())
        self.assertFalse(entry.exists())
        result = self.connect(entry, skills, '--adopt-bootstrap')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(bootstrap.is_symlink())
        backups = list((skills.parent / 'ai-memory-kit-backups').glob('ai-memory-kit-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'user-note.txt').read_text(), '我的补充')

    def test_unknown_install_does_not_modify_entry(self):
        skills = self.base / 'skills'
        (skills / 'ai-memory-kit').mkdir(parents=True)
        entry = self.base / 'entry.md'
        entry.write_text('原规则\n')
        result = self.connect(entry, skills, '--adopt-bootstrap')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(entry.read_text(), '原规则\n')

    def test_entry_symlink_needs_explicit_permission(self):
        target = self.base / 'shared.md'
        target.write_text('原规则\n')
        entry = self.base / 'entry.md'
        entry.symlink_to(target)
        skills = self.base / 'skills'
        self.assertEqual(self.connect(entry, skills).returncode, 2)
        self.assertEqual(target.read_text(), '原规则\n')
        self.assertFalse(skills.exists())
        self.assertEqual(self.connect(entry, skills, '--follow-symlink').returncode, 0)
        self.assertTrue(entry.is_symlink())

    def test_broken_marker_preserves_tail(self):
        entry = self.base / 'entry.md'
        original = '原规则\n<!-- ai-memory-kit:start -->\n必须保留的尾部\n'
        entry.write_text(original)
        self.assertEqual(self.connect(entry, self.base / 'skills').returncode, 2)
        self.assertEqual(entry.read_text(), original)

    def test_foreign_link_not_removed(self):
        other = self.base / 'other/.kit/ai-memory-kit'
        other.mkdir(parents=True)
        skills = self.base / 'skills'
        skills.mkdir()
        link = skills / 'ai-memory-kit'
        link.symlink_to(other)
        result = self.run_script('connect_agent.py', '--vault', str(self.vault), '--skills-dir', str(skills), '--no-entry', '--remove')
        self.assertEqual(result.returncode, 2)
        self.assertTrue(link.is_symlink())

    def test_copy_fallback_can_be_updated(self):
        skills = self.base / 'tool/skills'
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(Path, 'symlink_to', side_effect=OSError('模拟不支持链接')):
            self.assertEqual(connect_agent.update_skill(skills, self.vault, False, False), 0)
            installed = skills / 'ai-memory-kit'
            self.assertTrue((installed / connect_agent.OWNER).is_file())
            source = self.vault / '.kit/ai-memory-kit/SKILL.md'
            source.write_text(source.read_text() + '\nnew version\n')
            self.assertEqual(connect_agent.update_skill(skills, self.vault, False, False), 0)
            self.assertTrue((installed / 'SKILL.md').read_text().endswith('new version\n'))
        self.assertEqual(len(list((skills.parent / 'ai-memory-kit-backups').iterdir())), 1)

    def test_status_checks_actual_entry_and_managed_copy(self):
        entry = self.base / 'entry.md'
        skills = self.base / 'tool/skills'
        entry.write_text('<!-- ai-memory-kit:start -->\n旧库的入口\n<!-- ai-memory-kit:end -->\n')
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(Path, 'symlink_to', side_effect=OSError('模拟')):
            self.assertEqual(connect_agent.update_skill(skills, self.vault, False, False), 0)
        output = io.StringIO()
        with mock.patch.object(connect_agent, 'AGENTS', {'fixture': {'entry': str(entry), 'skills': str(skills)}}), contextlib.redirect_stdout(output):
            connect_agent.status(self.vault)
        self.assertIn('入口 需更新', output.getvalue())
        self.assertIn('受管理副本', output.getvalue())

    def test_failure_does_not_remove_racing_unknown_directory(self):
        skills = self.base / 'skills'
        link = skills / 'ai-memory-kit'
        def competing_directory(*args, **kwargs):
            link.mkdir()
            (link / 'keep.txt').write_text('并发产生的其他内容')
            raise FileExistsError('模拟目标被占用')
        with mock.patch.object(Path, 'symlink_to', side_effect=competing_directory), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(connect_agent.update_skill(skills, self.vault, False, False), 2)
        self.assertEqual((link / 'keep.txt').read_text(), '并发产生的其他内容')

    def test_failed_skill_creation_restores_entry(self):
        entry, skills = self.base / 'entry.md', self.base / 'skills'
        entry.write_text('原有规则\n')
        args = ['connect', '--vault', str(self.vault), '--entry', str(entry), '--skills-dir', str(skills)]
        with mock.patch.object(sys, 'argv', args), mock.patch.object(Path, 'symlink_to', side_effect=OSError('模拟')), mock.patch.object(shutil, 'copytree', side_effect=OSError('模拟复制失败')), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(connect_agent.main(), 2)
        self.assertEqual(entry.read_text(), '原有规则\n')
        self.assertFalse((skills / 'ai-memory-kit').exists())

    def test_disconnect_keeps_rules_and_memory(self):
        entry, skills = self.base / 'entry.md', self.base / 'skills'
        entry.write_text('原有规则\n')
        self.assertEqual(self.connect(entry, skills).returncode, 0)
        self.assertEqual(self.connect(entry, skills, '--remove').returncode, 0)
        self.assertEqual(entry.read_text(), '原有规则\n')
        self.assertFalse((skills / 'ai-memory-kit').exists())
        self.assertTrue((self.vault / '00-索引/AI启动卡.md').is_file())

    def local_sources(self):
        user = self.base / 'fake-user'
        rules = user / '.claude/CLAUDE.md'
        rules.parent.mkdir(parents=True)
        rules.write_text('用户是设计师\n')
        project = user / '.claude/projects/example/memory/MEMORY.md'
        project.parent.mkdir(parents=True)
        project.write_text('OTHER_PROJECT_CONTENT_MUST_STAY_UNREAD\n')
        return user, rules, project

    def test_import_lists_without_reading(self):
        user, rules, project = self.local_sources()
        result = self.run_script('import_existing.py', '--agent', 'claude', '--source-home', str(user), '--list')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(json.loads(result.stdout)['sources']), 2)
        self.assertNotIn('用户是设计师', result.stdout)
        self.assertNotIn('OTHER_PROJECT_CONTENT_MUST_STAY_UNREAD', result.stdout)

    def test_import_reads_only_selected_file(self):
        user, rules, project = self.local_sources()
        result = self.run_script('import_existing.py', '--agent', 'claude', '--source-home', str(user), '--source', str(rules))
        self.assertEqual(result.returncode, 0)
        self.assertIn('用户是设计师', result.stdout)
        self.assertNotIn('OTHER_PROJECT_CONTENT_MUST_STAY_UNREAD', result.stdout)
        self.assertEqual(project.read_text(), 'OTHER_PROJECT_CONTENT_MUST_STAY_UNREAD\n')

    def test_import_requires_selection(self):
        user, _, _ = self.local_sources()
        result = self.run_script('import_existing.py', '--agent', 'claude', '--source-home', str(user))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('用户是设计师', result.stdout)

    def test_import_rejects_credentials_outside_discovery(self):
        user, _, _ = self.local_sources()
        auth = user / '.claude/auth.json'
        auth.write_text('DO_NOT_READ_AUTH')
        result = self.run_script('import_existing.py', '--agent', 'claude', '--source-home', str(user), '--source', str(auth))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('DO_NOT_READ_AUTH', result.stdout)

    def test_manual_mode_and_credential_redaction(self):
        summary = self.base / 'intro.txt'
        synthetic = 's' + 'k' + '-' + 'SYNTHETIC_ONLY_1234567890' * 2
        summary.write_text('我是做内容的，喜欢先给结论。\napi_key: ' + synthetic)
        result = self.run_script('import_existing.py', '--manual-file', str(summary))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['mode'], 'manual')
        self.assertIn('先给结论', result.stdout)
        self.assertNotIn(synthetic, result.stdout)

    def test_pending_record_not_promoted_without_confirmation(self):
        before = (self.vault / '00-索引/AI启动卡.md').read_bytes()
        record = self.record()
        self.assertNotEqual(self.apply(record).returncode, 0)
        self.assertEqual((self.vault / '00-索引/AI启动卡.md').read_bytes(), before)
        self.assertFalse((self.vault / '00-索引/.已确认记录.json').exists())
        self.assertEqual(self.apply(record, '--dry-run').returncode, 0)
        self.assertEqual((self.vault / '00-索引/AI启动卡.md').read_bytes(), before)

    def test_preference_and_correction_update_card_immediately(self):
        card = self.vault / '00-索引/AI启动卡.md'
        card.write_text('# 我是谁\n用户手写内容，保留。\n周报以前用表格。\n')
        first = self.record(summary='周报使用表格')
        self.assertEqual(self.apply(first, '--confirmed').returncode, 0)
        corrected = self.record('correction', summary='周报使用自然段')
        self.assertEqual(self.apply(corrected, '--confirmed').returncode, 0)
        self.assertIn('周报使用自然段', card.read_text())
        self.assertNotIn('周报使用表格', card.read_text())
        self.assertIn('用户手写内容，保留。', card.read_text())
        self.assertIn('覆盖同主题旧摘要', card.read_text())
        self.assertIn('周报使用自然段', (self.vault / '01-用户记忆/长期偏好.md').read_text())

    def test_project_decision_and_experience_keep_provenance(self):
        record = self.record('decision', summary='先确认音频再做画面', key='制作顺序', scope='project', project='教学视频', reason='避免文案修改造成返工')
        self.assertEqual(self.apply(record, '--confirmed').returncode, 0)
        experience = self.record('experience', summary='先定音频的方法', key='制作经验', scope='project', project='教学视频', result='本次画面修改减少', conditions='口播解释视频')
        self.assertEqual(self.apply(experience, '--confirmed').returncode, 0)
        project = (self.vault / '02-项目/教学视频.md').read_text()
        for item in ('先确认音频', '避免文案修改', '本次画面修改减少', '口播解释视频', '用户明确确认'):
            self.assertIn(item, project)
        self.assertIn('教学视频.md', (self.vault / '00-索引/项目索引.md').read_text())
        self.assertEqual(len(list((self.vault / '03-每日记录/记忆').glob('*.md'))), 2)

    def set_record_time(self, record_id, timestamp):
        path = self.vault / ('00-索引/待处理/' + record_id + '.json')
        record = json.loads(path.read_text())
        record['recorded_at'] = timestamp
        path.write_text(json.dumps(record, ensure_ascii=False))

    def test_delayed_old_confirmation_does_not_undo_correction(self):
        old = self.record(summary='周报使用表格')
        new = self.record('correction', summary='周报使用自然段')
        self.set_record_time(old, '2026-10-12T12:00:00+08:00')
        self.set_record_time(new, '2026-10-13T12:00:00+08:00')
        self.assertEqual(self.apply(new, '--confirmed').returncode, 0)
        self.assertEqual(self.apply(old, '--confirmed').returncode, 0)
        for relative in ('00-索引/AI启动卡.md', '01-用户记忆/长期偏好.md'):
            text = (self.vault / relative).read_text()
            self.assertIn('周报使用自然段', text)
            self.assertNotIn('周报使用表格', text)
        self.assertEqual(len(list((self.vault / '03-每日记录/记忆').glob('*.md'))), 2)
        renewed = self.record(summary='周报使用表格')
        self.assertEqual(self.apply(renewed, '--confirmed').returncode, 0)
        self.assertIn('周报使用表格', (self.vault / '00-索引/AI启动卡.md').read_text())

    def test_equal_timestamp_correction_overrides_preference(self):
        old = self.record(summary='周报使用表格')
        new = self.record('correction', summary='周报使用自然段')
        for record in (old, new):
            self.set_record_time(record, '2026-10-13T12:00:00+08:00')
        self.assertEqual(self.apply(new, '--confirmed').returncode, 0)
        self.assertEqual(self.apply(old, '--confirmed').returncode, 0)
        self.assertIn('周报使用自然段', (self.vault / '00-索引/AI启动卡.md').read_text())

    def test_equal_timestamp_conflict_preserves_current_view(self):
        first = self.record(summary='周报使用表格')
        second = self.record(summary='周报使用自然段')
        for record in (first, second):
            self.set_record_time(record, '2026-10-13T12:00:00+08:00')
        self.assertEqual(self.apply(first, '--confirmed').returncode, 0)
        card = self.vault / '00-索引/AI启动卡.md'
        before = card.read_bytes()
        self.assertEqual(self.apply(second, '--confirmed').returncode, 2)
        self.assertEqual(card.read_bytes(), before)
        state = json.loads((self.vault / '00-索引/.已确认记录.json').read_text())
        self.assertNotIn(second, state['records'])

    def test_invalid_record_timestamp_is_not_applied(self):
        record = self.record()
        self.set_record_time(record, '2026-10-13T12:00:00')
        self.assertEqual(self.apply(record, '--confirmed').returncode, 2)
        self.assertFalse((self.vault / '00-索引/.已确认记录.json').exists())

    def test_missing_decision_reason_is_not_invented(self):
        result = self.run_script('record_memory.py', '--vault', str(self.vault), '--kind', 'decision', '--scope', 'project', '--project', '项目', '--summary', '一个决定', '--agent', '测试', '--source', '用户')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.vault / '00-索引/待处理').exists())

    def test_project_memory_not_promoted_globally(self):
        record = self.record('decision', summary='本视频用蓝色', key='颜色', scope='project', project='单条视频', reason='本次选择')
        self.assertEqual(self.apply(record, '--confirmed').returncode, 0)
        self.assertNotIn('本视频用蓝色', (self.vault / '01-用户记忆/长期偏好.md').read_text())
        self.assertIn('项目 单条视频', (self.vault / '00-索引/AI启动卡.md').read_text())

    def test_repeat_apply_does_not_duplicate_history(self):
        record = self.record()
        self.assertEqual(self.apply(record, '--confirmed').returncode, 0)
        before = (self.vault / '00-索引/AI启动卡.md').read_bytes()
        result = self.apply(record, '--confirmed')
        self.assertEqual(json.loads(result.stdout)['status'], 'already_applied')
        self.assertEqual((self.vault / '00-索引/AI启动卡.md').read_bytes(), before)
        self.assertEqual(len(list((self.vault / '03-每日记录/记忆').glob('*.md'))), 1)

    def test_refresh_restores_confirmed_card_after_review(self):
        record = self.record()
        self.assertEqual(self.apply(record, '--confirmed').returncode, 0)
        card = self.vault / '00-索引/AI启动卡.md'
        card.write_text('# 人工复盘摘要\n保留这段。\n')
        result = self.run_script('apply_memory.py', '--vault', str(self.vault), '--refresh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('保留这段。', card.read_text())
        self.assertIn('周报使用自然段', card.read_text())

    def test_withdrawal_keeps_history_and_replaces_active_requirement(self):
        first = self.record(summary='周报使用表格')
        self.assertEqual(self.apply(first, '--confirmed').returncode, 0)
        withdrawn = self.record('withdrawal', summary='不再要求周报使用表格')
        self.assertEqual(self.apply(withdrawn, '--confirmed').returncode, 0)
        card = (self.vault / '00-索引/AI启动卡.md').read_text()
        self.assertIn('已撤销旧要求', card)
        self.assertEqual(len(list((self.vault / '03-每日记录/记忆').glob('*.md'))), 2)

    def test_all_confirmed_global_topics_remain_on_card(self):
        # No old global correction can disappear just because later project notes were added.
        for i in range(13):
            record = self.record(summary='明确要求' + str(i), key='主题' + str(i))
            self.assertEqual(self.apply(record, '--confirmed').returncode, 0)
        card = (self.vault / '00-索引/AI启动卡.md').read_text()
        self.assertIn('主题0：明确要求0', card)
        self.assertIn('主题12：明确要求12', card)

    def test_two_process_records_do_not_overwrite(self):
        args = ['--vault', str(self.vault), '--kind', 'preference', '--scope', 'global', '--agent', '测试', '--source', '用户']
        a = self.run_script('record_memory.py', *args, '--key', '格式', '--summary', '先给结论')
        b = self.run_script('record_memory.py', *args, '--key', '语言', '--summary', '用中文')
        self.assertEqual(a.returncode, 0)
        self.assertEqual(b.returncode, 0)
        self.assertNotEqual(json.loads(a.stdout)['record_id'], json.loads(b.stdout)['record_id'])
        inbox = (self.vault / '00-索引/收件箱.md').read_text()
        self.assertIn('先给结论', inbox)
        self.assertIn('用中文', inbox)

    def test_lock_contention_does_not_take_other_lock(self):
        lock = self.vault / '00-索引/.整理中'
        lock.write_text('{"token":"another-process"}')
        result = self.run_script('record_memory.py', '--vault', str(self.vault), '--kind', 'preference', '--scope', 'global', '--summary', '先给结论', '--agent', '测试', '--source', '用户')
        self.assertEqual(result.returncode, 75)
        self.assertEqual(lock.read_text(), '{"token":"another-process"}')

    def test_record_refuses_credential_like_content(self):
        value = 's' + 'k' + '-' + 'SYNTHETIC_ONLY_1234567890' * 2
        result = self.run_script('record_memory.py', '--vault', str(self.vault), '--kind', 'preference', '--scope', 'global', '--summary', 'api_key: ' + value, '--agent', '测试', '--source', '用户')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(value, result.stderr)
        self.assertFalse((self.vault / '00-索引/待处理').exists())

    def test_record_scope_cannot_escape_vault(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.vault / '00-索引/待处理').symlink_to(outside)
        result = self.run_script('record_memory.py', '--vault', str(self.vault), '--kind', 'preference', '--scope', 'global', '--summary', '先给结论', '--agent', '测试', '--source', '用户')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_weekly_review_date_not_file_mtime(self):
        (self.vault / '04-每周复盘/2020-W01.md').write_text('# 旧复盘\n')
        result = self.run_script('check_vault.py', '--path', str(self.vault))
        self.assertEqual(result.returncode, 1)
        self.assertIn('距覆盖周结束', result.stdout)
        self.assertNotIn('距今 0 天', result.stdout)

    def test_initial_template_health(self):
        result = self.run_script('check_vault.py', '--path', str(self.vault))
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    unittest.main()
