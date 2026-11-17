"""RC-02 fixture fidelity and fail-closed guards; no external database access."""
import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import pytest
from rc02_sample import HEADERS, synthetic_feed

ROOT=Path(__file__).resolve().parents[2]


def test_rc02_sample_reproduces_declared_structure_without_customer_records():
    data=synthetic_feed()
    assert data.startswith(b'\xef\xbb\xbf')
    rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig')),delimiter=';'))
    assert rows[0]==HEADERS and len(HEADERS)==27
    assert len(rows[1:])==4948 and all(len(r)==27 for r in rows)
    nonempty=[r for r in rows[1:] if any(x.strip() for x in r)]
    assert len(nonempty)==3 and len(rows[1:])-len(nonempty)==4945
    assert [r[0] for r in nonempty]==['RC02-001','RC02-002','RC02-003']
    assert [r[3] for r in nonempty]==['-35132','-710','-16920']
    assert nonempty[0][2]=='8,71999E+12'
    assert nonempty[0][4:7]==['405,51','589,7637795','HUF']


@pytest.mark.parametrize('ack,url',[
    ('','mysql+pymysql://fixture:dummy@127.0.0.1:1/adatdusito_dev'),
    ('isolated-release-candidate-02','mysql+pymysql://fixture:dummy@vps.invalid/adatdusito_dev'),
    ('isolated-release-candidate-02','mysql+pymysql://fixture:dummy@127.0.0.1:1/pinfo_db'),
    ('isolated-release-candidate-02','sqlite://'),
])
def test_mysql_import_probe_rejects_unsafe_targets_before_connecting(ack,url):
    env=dict(os.environ,RC02_FIXTURE_ACK=ack,APP_DATABASE_URL=url)
    result=subprocess.run([sys.executable,str(ROOT/'scripts/mysql_rc02_import_check.py')],env=env,
                          capture_output=True,text=True,timeout=10)
    assert result.returncode!=0
    assert 'Refusing:' in result.stderr
    assert 'dummy' not in result.stderr and 'OperationalError' not in result.stderr
