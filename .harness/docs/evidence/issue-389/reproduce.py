#!/usr/bin/env python3
"""Воспроизвести ограниченные проверки #389 на disposable initialized consumer.

Запускать выбранным Python из проверяемого checkout. Без аргументов Python 3.13
выполняет 11 прежних execution-тестов и пять регрессий, остальные версии —
high-risk и fixture regression. Аргументы ограничивают набор именами self-tests.
JSON и логи сохраняются в системном временном каталоге; retries отсутствуют.
"""
import importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[4]
# Дочерние canonical команды используют python3: закрепляем ту же версию,
# иначе self-test на 3.11 мог бы запускать verification-команды системным Python.
os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
assert subprocess.check_output(["python3", "-c", "import sys; print(sys.version)"], text=True).strip() == sys.version
sys.path.insert(0,str(SOURCE/'.harness/tools'))
def load(name,path):
    """Загрузить реальные helpers текущего installed checkout без замены Core."""
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
fixture=load('fixture_test',SOURCE/'.harness/tools/self-test-fixture-self-test.py')
runner=load('self_test_runner',SOURCE/'.harness/tools/run-self-tests.py')
import windows_ci
version=f'{sys.version_info.major}.{sys.version_info.minor}'
results=[]
with tempfile.TemporaryDirectory(prefix='harness-389-consumer-') as td:
    host=Path(td)/'consumer'
    fixture.verification_host(SOURCE,host,'policies/host-map.json')
    for number in range(1900):
        fixture.write(host/f'product/module-{number:04d}.txt','x'*14000)
    fixture.run(host,'git','add','product')
    fixture.run(host,'git','commit','-qm','Добавить масштаб consumer для issue 389')
    runtime=host/'.harness/tools/verification.py'
    fixture.write(runtime,runtime.read_text()+'\n# Изменённый installed runtime.\n')
    fixture.write(host/'.harness/tools/issue-389-managed.py','# Новый managed файл.\n')
    fixture.run(host,sys.executable,'.harness/tools/validate.py','--mode','ci')
    files=[p for p in host.rglob('*') if p.is_file() and '.git' not in p.relative_to(host).parts]
    scale={'files':len(files),'bytes':sum(p.stat().st_size for p in files)}
    names=([name for group in ('execution','verification','incremental','manual','high-risk') for name in windows_ci.GROUPS[group]] if version=='3.13' else ['verification-high-risk','self-test-fixture','late-defect'])
    if version=='3.13': names+=['self-test-fixture','windows-ci','run-self-tests','verification-review-regressions','late-defect']
    if len(sys.argv)>1: names=sys.argv[1:]
    for name in names:
        item,out,err=runner.run_one(host/'.harness/tools'/f'{name}-self-test.py',repo_root=host,timeout_seconds=120)
        results.append(item)
        (Path(tempfile.gettempdir()) / f'harness-389-{version}-{name}.log').write_text(out+'\n'+err)
        print(json.dumps(item),flush=True)
        if item['status']!='PASS': print(out[-3000:],err[-3000:],flush=True)
report={'python':sys.version,'platform':sys.platform,'scale':scale,'timeoutSeconds':120,'results':results}
(Path(tempfile.gettempdir()) / (f'harness-389-{version}' + ('-targeted' if len(sys.argv)>1 else '') + '.json')).write_text(json.dumps(report,indent=2) + '\n')
raise SystemExit(0 if all(r['status']=='PASS' for r in results) else 1)
