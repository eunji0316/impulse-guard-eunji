"""
실제 DB에서 학습 데이터 추출 (generate.py와 같은 열)

- 대상: 결과가 정해진 쿨다운 (failed=1, gaveup/success=0). waiting은 뺀다
- 거래(g5_ipp_transaction)로 회원 평균 대비 금액 비율을, 차단 기록(g5_ipp_block_log)으로 업종/체류 시간/방문 수를 만든다
- SELECT만 한다. DB를 바꾸지 않는다
- 개인정보: 회원 아이디는 실행할 때마다 새로 만든 salt로 HMAC해서 남기고, 상품명은 남기지 않는다(has_pressure만).
  만든 CSV는 Git에 올리지 않는다 (ai/.gitignore)

DB 접속 정보는 그누보드의 data/dbconfig.php에서 읽는다. 환경변수 IPP_DB_HOST, IPP_DB_USER, IPP_DB_PASSWORD,
IPP_DB_NAME, IPP_DB_PREFIX가 있으면 그 값을 쓴다.

사용: python data/export.py [--out data/real.csv] [--dbconfig ../data/dbconfig.php]
"""
import argparse
import hashlib
import hmac
import os
import re
import sys
from datetime import timedelta

import pandas as pd
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import features as F  # noqa: E402
from describe import summary  # noqa: E402

MATCH_WINDOW = timedelta(hours=1)   # 쿨다운과 같은 상품의 차단 기록을 이 시간 안에서 찾는다


def read_dbconfig(path):
    """dbconfig.php의 define('G5_MYSQL_*', '...')과 G5_TABLE_PREFIX 읽기"""
    with open(path, encoding='utf-8') as f:
        src = f.read()
    found = {k: v.replace("\\'", "'").replace('\\\\', '\\')
             for k, v in re.findall(r"define\(\s*'(G5_MYSQL_\w+|G5_TABLE_PREFIX)'\s*,\s*'((?:[^'\\]|\\.)*)'", src)}
    return {
        'host':     os.environ.get('IPP_DB_HOST', found.get('G5_MYSQL_HOST', 'localhost')),
        'user':     os.environ.get('IPP_DB_USER', found.get('G5_MYSQL_USER', '')),
        'password': os.environ.get('IPP_DB_PASSWORD', found.get('G5_MYSQL_PASSWORD', '')),
        'database': os.environ.get('IPP_DB_NAME', found.get('G5_MYSQL_DB', '')),
        'prefix':   os.environ.get('IPP_DB_PREFIX', found.get('G5_TABLE_PREFIX', 'g5_')),
    }


def load(conn, prefix):
    """필요한 세 테이블을 읽는다. 쿨다운 회원의 기록만 가져온다"""
    def q(sql, params=()):
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return pd.DataFrame(cur.fetchall())

    status = tuple(F.LABELS)
    cd = q(f"SELECT cd_id, mb_id, cd_source, tr_id, cd_item_name, cd_amount, cd_status, cd_start_datetime "
           f"FROM {prefix}ipp_cooldown WHERE cd_status IN %s ORDER BY cd_start_datetime", (status,))
    if cd.empty:
        return cd, pd.DataFrame(), pd.DataFrame()

    members = tuple(cd.mb_id.unique())
    tr = q(f"SELECT tr_id, mb_id, tr_amount, tr_category, tr_datetime FROM {prefix}ipp_transaction "
           f"WHERE tr_type = 'pay' AND mb_id IN %s", (members,))
    bl = q(f"SELECT mb_id, bl_site, bl_item_name, bl_event, bl_stay_sec, bl_datetime FROM {prefix}ipp_block_log "
           f"WHERE mb_id IN %s", (members,))
    return cd, tr, bl


def nearest(rows, when):
    """when과 가장 가까운 시각의 행. 없으면 None"""
    if rows.empty:
        return None
    return rows.loc[(rows.bl_datetime - when).abs().idxmin()]


def build(cd, tr, bl, salt):
    out = []
    for c in cd.itertuples():
        start = c.cd_start_datetime

        # 회원 평균 대비 금액 비율: 직전 RATIO_WINDOW_DAYS일 결제
        past = tr[(tr.mb_id == c.mb_id) & (tr.tr_datetime < start)
                  & (tr.tr_datetime >= start - timedelta(days=F.RATIO_WINDOW_DAYS))]

        # 같은 회원, 같은 상품명, 앞뒤 1시간의 차단 기록 (확장 프로그램에서 만든 쿨다운이면 있다)
        mine = bl[(bl.mb_id == c.mb_id) & (bl.bl_item_name == c.cd_item_name)
                  & ((bl.bl_datetime - start).abs() <= MATCH_WINDOW)]
        any_log = nearest(mine, start)
        visit   = nearest(mine[mine.bl_event == 'visit'], start)

        # 업종: 사후 감지면 거래의 업종, 확장 프로그램이면 쇼핑몰, 모르면 etc
        category = 'etc'
        if c.cd_source == 'detect' and pd.notna(c.tr_id):
            t = tr[tr.tr_id == c.tr_id]
            if not t.empty and t.iloc[0].tr_category in F.CATEGORIES:
                category = t.iloc[0].tr_category
        elif any_log is not None:
            category = 'shopping'   # 차단 사이트는 모두 쇼핑몰 (ipp/api/ext.php check와 같은 기준)

        # 직전 24시간 같은 사이트 방문 수
        visits = 0
        if any_log is not None:
            visits = int(((bl.mb_id == c.mb_id) & (bl.bl_site == any_log.bl_site) & (bl.bl_event == 'visit')
                          & (bl.bl_datetime < start)
                          & (bl.bl_datetime >= start - timedelta(hours=F.VISIT_WINDOW_HOURS))).sum())

        out.append({
            'user':              hmac.new(salt, c.mb_id.encode('utf-8'), hashlib.sha256).hexdigest()[:12],
            'hour':              start.hour,
            'weekday':           start.weekday(),
            'amount':            int(c.cd_amount),
            'amount_ratio':      F.amount_ratio(c.cd_amount, past.tr_amount.tolist()),
            'category':          category,
            'has_pressure':      F.has_pressure(c.cd_item_name),
            'stay_sec':          int(visit.bl_stay_sec) if visit is not None else None,
            'visits_24h':        visits,
            'days_since_payday': F.days_since_payday(start),
            'label':             F.LABELS[c.cd_status],
        })

    df = pd.DataFrame(out, columns=F.COLUMNS)
    df['stay_sec'] = df.stay_sec.astype('Int64')
    return df


def main():
    ap = argparse.ArgumentParser(description='실제 DB에서 충동구매 학습 데이터 추출')
    ap.add_argument('--out', default=os.path.join(HERE, 'real.csv'))
    ap.add_argument('--dbconfig', default=os.path.join(HERE, '..', '..', 'data', 'dbconfig.php'))
    args = ap.parse_args()

    cfg = read_dbconfig(args.dbconfig)
    conn = pymysql.connect(host=cfg['host'], user=cfg['user'], password=cfg['password'],
                           database=cfg['database'], charset='utf8mb4')
    try:
        cd, tr, bl = load(conn, cfg['prefix'])
    finally:
        conn.close()

    df = build(cd, tr, bl, os.urandom(16))
    df.to_csv(args.out, index=False, encoding='utf-8')
    print('저장:', args.out)
    if df.empty:
        print('정답 데이터가 없습니다. 결과가 정해진 쿨다운(failed/gaveup/success)이 쌓이면 다시 실행하세요.')
        return
    print('정답 분포:', df.label.value_counts().to_dict())
    summary(df)


if __name__ == '__main__':
    main()
