#!/usr/bin/env python3
"""Регрессии #334: очистка допустима только после доказанного завершения владельца."""
from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

import local_cleanup as cleaner
from command_dispatch import start_dispatch, complete_dispatch, resume_dispatch
from execution_status import (start_execution, complete_command, load_status, save_status,
                              execution_state_lock, begin_command)
from self_test_fixture import copy_effective_harness_checkout

SOURCE = Path(__file__).resolve().parents[2]
COMMAND = 'GITHUB GENERATE TEMPLATES'


def contents(root: Path) -> dict:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def fixture(root: Path) -> None:
    copy_effective_harness_checkout(SOURCE, root)


def handoff(root: Path) -> tuple[dict, Path]:
    value = start_dispatch(root, COMMAND)
    assert value['status'] == 'SEMANTIC', value
    path = root / value['temporaryDirectory']
    (path / 'before.txt').write_text('временный снимок', encoding='utf-8')
    return value, path


def finish(root: Path, value: dict, result: str = 'SUCCESS') -> dict:
    return complete_dispatch(root, COMMAND, COMMAND, result, execution_id=value['executionId'])


def reason(root: Path, path: Path) -> str:
    report = cleaner.cleanup(root)
    return next(entry['reasonCode'] for entry in report['candidates'] if entry['path'] == str(path.relative_to(root)).replace('\\', '/'))


def checkpoint(root: Path, value: dict) -> None:
    # Воспроизводим crash после durable completion, но до dispatcher cleanup.
    complete_command(root, COMMAND, COMMAND, 'SUCCESS', expected_execution_id=value['executionId'])


def concurrent_apply(root: str, ready, done) -> None:
    ready.set()
    result = cleaner.cleanup(Path(root), apply=True)
    assert result['status'] == 'PASS', result
    done.set()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='harness-cleanup-') as tmp:
        root = Path(tmp) / 'project'; root.mkdir(); fixture(root)
        before = contents(root)
        checked = start_dispatch(root, 'HARNESS CLEANUP CHECK')
        assert checked['status'] == 'DONE' and contents(root) == before, checked
        assert not (root / '.harness/local').exists()

        value, path = handoff(root)
        before = contents(root)
        assert reason(root, path) == 'OWNER_NOT_COMPLETE'
        assert cleaner.cleanup(root, apply=True)['status'] == 'PASS' and path.exists()
        assert contents(root) == before
        resumed = resume_dispatch(root, COMMAND)
        assert resumed['executionId'] == value['executionId'] and resumed['temporaryDirectory'] == value['temporaryDirectory']
        finished = finish(root, value)
        assert finished['status'] == 'DONE' and not path.exists(), finished
        assert cleaner.cleanup(root, apply=True)['candidates'] == []

        # Failed/blocked владельцы и неизвестные старые namespaces сохраняются.
        failed, failed_path = handoff(root)
        finish(root, failed, 'FAIL')
        assert failed_path.exists() and reason(root, failed_path) == 'OWNER_NOT_COMPLETE'
        legacy = root / '.harness/local/step-old/before.log'; legacy.parent.mkdir(); legacy.write_text('legacy')
        unknown = root / cleaner.BASE / 'exec-unknown'; unknown.mkdir()
        cleaner.cleanup(root, apply=True)
        assert legacy.exists() and unknown.exists()

        value, path = handoff(root); checkpoint(root, value)
        before = contents(root)
        assert reason(root, path) == 'ELIGIBLE' and contents(root) == before
        # Изменение после preview проверяется заново; новая canonical ссылка защищает каталог.
        reference = root / 'planning/tasks/cleanup-reference.md'
        reference.write_text(f'Сохранённый результат: {value["temporaryDirectory"]}/before.txt', encoding='utf-8')
        assert reason(root, path) == 'CANONICAL_REFERENCE'
        cleaner.cleanup(root, apply=True); assert path.exists()
        reference.unlink()
        result = start_dispatch(root, 'HARNESS CLEANUP APPLY')
        assert result['status'] == 'DONE' and not path.exists(), result

        # Configured relocation тоже проверяется, без привязки к planning/tasks.
        manifest = root / '.harness/manifest.yaml'; original = manifest.read_text(encoding='utf-8')
        manifest.write_text(original.replace('taskDirectory: planning/tasks', 'taskDirectory: custom/tasks'), encoding='utf-8')
        reference = root / 'custom/tasks/evidence.md'; reference.parent.mkdir(parents=True)
        value, path = handoff(root); checkpoint(root, value)
        reference.write_text(value['executionId'], encoding='utf-8')
        assert reason(root, path) == 'CANONICAL_REFERENCE'
        reference.write_bytes(b'\xff')
        assert reason(root, path) == 'REFERENCES_UNAVAILABLE'
        reference.unlink(); manifest.write_text(original, encoding='utf-8')
        cleaner.cleanup(root, apply=True); assert not path.exists()

        value, path = handoff(root); checkpoint(root, value)
        state = load_status(root)
        state['recentTerminals'] = [item for item in state['recentTerminals'] if item['executionId'] != value['executionId']]
        save_status(root, state)
        assert reason(root, path) == 'OWNER_PROOF_MISSING'
        cleaner.cleanup(root, apply=True); assert path.exists()

        # Ни чужой занятый путь, ни копия маркера не дают права владения.
        live = start_execution(root, COMMAND); occupied = root / cleaner.BASE / live['executionId']; occupied.mkdir()
        try:
            cleaner.temporary_directory(root, live['executionId'])
            raise AssertionError('чужой каталог принят')
        except (ValueError, OSError):
            pass
        try:
            cleaner.temporary_directory(root, '../escape')
            raise AssertionError('неверный executionId принят')
        except ValueError:
            pass
        complete_command(root, COMMAND, COMMAND, 'FAIL', expected_execution_id=live['executionId'])

        value, path = handoff(root); checkpoint(root, value)
        snapshot = cleaner.tree_snapshot(path)
        (path / 'before.txt').write_text('изменено', encoding='utf-8')
        try:
            cleaner.remove_tree(root, path.name, snapshot)
            raise AssertionError('изменившийся кандидат удалён')
        except cleaner.CleanupError:
            pass
        assert path.exists()
        lock = path / 'consumer.lock'; lock.write_text('lock')
        assert reason(root, path) == 'LOCK_FILE'
        lock.unlink(); cleaner.cleanup(root, apply=True); assert not path.exists()

        # Ошибка вторичной уборки не отменяет SUCCESS основной команды.
        value, path = handoff(root)
        with patch.object(cleaner, 'remove_tree', side_effect=OSError('synthetic')):
            result = finish(root, value)
        assert result['status'] == 'DONE' and result['cleanup']['status'] == 'WARNING' and path.exists(), result
        # Resume уже завершённого root также убирает остаток после crash.
        result = resume_dispatch(root, COMMAND)
        assert result['status'] == 'DONE' and not path.exists(), result

        # UPDATE не позволяет APPLY получить lock; CHECK остаётся read-only.
        value, path = handoff(root); checkpoint(root, value)
        journal = root / '.harness/local/update-journal'; journal.mkdir()
        (journal / 'journal.json').write_text('{}')
        before = contents(root)
        assert cleaner.cleanup(root, apply=True)['status'] == 'WARNING' and contents(root) == before
        cleaner.cleanup(root); assert contents(root) == before
        shutil.rmtree(journal)
        cleaner.cleanup(root, apply=True); assert not path.exists()

        # Конкурентный canonical resume владеет тем же lock. Пока он занят,
        # APPLY не удаляет даже ранее допустимого кандидата.
        value, path = handoff(root); checkpoint(root, value)
        ctx = multiprocessing.get_context('spawn'); ready = ctx.Event(); done = ctx.Event()
        with execution_state_lock(root):
            worker = ctx.Process(target=concurrent_apply, args=(str(root), ready, done)); worker.start()
            assert ready.wait(15) and not done.wait(.3) and path.exists()
            # Подтверждённая активная зависимость сохраняет данные после release lock.
            active = start_execution(root, 'GIT COMMIT')
            state = load_status(root)
            next(item for item in state['executions'] if item['executionId'] == active['executionId'])['current']['context']['temporaryDependency'] = value['executionId']
            save_status(root, state)
        worker.join(20); assert worker.exitcode == 0 and done.is_set() and path.exists()
        assert reason(root, path) == 'ACTIVE_DEPENDENCY'
        complete_command(root, 'GIT COMMIT', 'GIT COMMIT', 'FAIL', expected_execution_id=active['executionId'])

        # Листовые и родительские symlinks/junctions не открывают выход из tmp.
        outside = Path(tmp) / 'outside'; outside.mkdir(); sentinel = outside / 'keep'; sentinel.write_text('keep')
        link = root / cleaner.BASE / ('exec-' + 'f' * 32)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                raise
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
        assert reason(root, link) == 'UNSAFE_LINK'
        cleaner.cleanup(root, apply=True); assert sentinel.read_text() == 'keep'
        if os.name == 'nt' and not link.is_symlink():
            os.rmdir(link)
        else:
            link.unlink()
        parent = root / cleaner.BASE; held = parent.with_name('tmp-held'); parent.rename(held)
        try:
            parent.symlink_to(outside, target_is_directory=True)
        except OSError:
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(parent), str(outside)], check=True, capture_output=True)
        assert cleaner.cleanup(root, apply=True)['status'] == 'WARNING' and sentinel.exists()
        if os.name == 'nt' and not parent.is_symlink():
            os.rmdir(parent)
        else:
            parent.unlink()
        held.rename(parent)

        if os.name != 'nt':
            # Подмена маркера после mkdir не перезаписывает внешние данные.
            owner = start_execution(root, COMMAND)
            original_open = os.open
            def marker_race(name, flags, *args, **kwargs):
                if name == cleaner.MARKER:
                    os.symlink(str(sentinel), name, dir_fd=kwargs['dir_fd'])
                return original_open(name, flags, *args, **kwargs)
            with patch.object(cleaner.os, 'open', side_effect=marker_race):
                try:
                    cleaner.temporary_directory(root, owner['executionId'])
                    raise AssertionError('подменённый marker принят')
                except OSError:
                    pass
            assert sentinel.read_text() == 'keep'
            complete_command(root, COMMAND, COMMAND, 'FAIL', expected_execution_id=owner['executionId'])

            # Подмена candidate в последнем capture сохраняет новое дерево.
            value, path = handoff(root); checkpoint(root, value)
            original_rename = os.rename
            moved = path.with_name('replaced-original')
            def capture_race(source, destination, *args, **kwargs):
                if source == path.name:
                    original_rename(path, moved)
                    path.mkdir(); (path / 'replacement').write_text('сохранить', encoding='utf-8')
                return original_rename(source, destination, *args, **kwargs)
            with patch.object(cleaner.os, 'rename', side_effect=capture_race):
                result = cleaner.cleanup(root, apply=True)
            assert result['status'] == 'WARNING' and moved.exists(), result
            retained = list((root / cleaner.BASE).glob('.cleanup-*/candidate/replacement'))
            assert len(retained) == 1 and retained[0].read_text(encoding='utf-8') == 'сохранить'

            # Старое имя leaf после capture больше не ведёт внутрь удаляемого дерева.
            value, path = handoff(root); checkpoint(root, value)
            original_unlink = os.unlink
            attempted = []
            def leaf_race(name, *args, **kwargs):
                if name == 'before.txt':
                    attempted.append(True)
                    assert not path.exists()
                    path.mkdir(); (path / 'before.txt').write_text('новые данные', encoding='utf-8')
                return original_unlink(name, *args, **kwargs)
            with patch.object(cleaner.os, 'unlink', side_effect=leaf_race):
                cleaner.cleanup(root, apply=True)
            assert attempted and (path / 'before.txt').read_text(encoding='utf-8') == 'новые данные'

        # STEP PLAN/IMPLEMENT success не заменяет completion proof всего STEP.
        spec = importlib.util.spec_from_file_location('execution_fixture', SOURCE / '.harness/tools/execution-self-test.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        task = root / 'planning/tasks/STEP-001.md'
        text = module.task().replace('type: implementation', 'type: research').replace('requirements:\n  - REQ-001', 'requirements: []')
        task.write_text(text, encoding='utf-8')
        owner = start_execution(root, 'STEP PLAN STEP-001')
        step_path = root / cleaner.temporary_directory(root, owner['executionId'])
        complete_command(root, 'STEP PLAN STEP-001', 'STEP PLAN STEP-001', 'SUCCESS', expected_execution_id=owner['executionId'])
        assert reason(root, step_path) == 'STEP_NOT_COMPLETE'
        task.write_text(text.replace('status: planned', 'status: completed').replace('## Evidence\n\n—', '## Evidence\n\nРезультат исследования сохранён.'), encoding='utf-8')
        assert cleaner.step_completion_proof(root, 'STEP-001')['complete']
        active = start_execution(root, 'STEP PLAN STEP-001')
        assert reason(root, step_path) == 'ACTIVE_DEPENDENCY'
        complete_command(root, 'STEP PLAN STEP-001', 'STEP PLAN STEP-001', 'FAIL', expected_execution_id=active['executionId'])
        assert reason(root, step_path) == 'ELIGIBLE', reason(root, step_path)
        cleaner.cleanup(root, apply=True); assert not step_path.exists()

        # Child CHECK внутри незавершённой цепочки не разрешает очистку root.
        chain = 'GIT CHECK > COMMIT'
        owner = start_execution(root, chain)
        chain_path = root / cleaner.temporary_directory(root, owner['executionId'])
        complete_command(root, chain, 'GIT CHECK', 'PASS', expected_execution_id=owner['executionId'])
        assert reason(root, chain_path) == 'OWNER_NOT_COMPLETE'
        assert cleaner.cleanup(root, apply=True)['status'] == 'PASS' and chain_path.exists()
    print('LOCAL CLEANUP SELF-TEST: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
