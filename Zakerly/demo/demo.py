#!/usr/bin/env python3
"""Demo data for the KFH Knowledge Assistant.

    demo.py load  --owner EMAIL   create the knowledge bases in manifest.json and upload documents/
    demo.py test  --owner EMAIL   ask the demo questions (saved as conversations of that user)
    demo.py reset                 delete the demo knowledge bases, their documents and embeddings

Talks to the running app through the frontend's /api proxy and to Postgres via `docker exec`.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = 'http://localhost:3001/api/v1'
MIME = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
MANIFEST = json.loads((HERE / 'manifest.json').read_text())

QUESTIONS = [  # (knowledge base, document title or None, topic or None, question)
    ('Retail Banking Products', None, None, 'What is the minimum amount to issue the El Aman certificate, and when can it be redeemed?'),
    ('Retail Banking Products', None, None, 'ما هو الحد الأقصى للتمويل الشخصي وما هي مدة السداد؟'),
    ('Cards & Digital Banking', 'Credit Cards', None, 'What are the grace period and minimum monthly payment on the Platinum credit card?'),
    ('Terms & Conditions', 'General Terms and Conditions for Accounts and Banking Services', 'account closure',
     'Under what conditions can the bank close a customer account?'),
    ('Terms & Conditions', 'الشروط والأحكام العامة للحسابات والخدمات المصرفية', None, 'ما هي الشروط الخاصة بالحسابات الجارية؟'),
    ('About KFH Egypt', 'KFH Egypt 2024 Sustainability Report', None, 'How many branches and ATMs did KFH Egypt have in 2024?'),
    ('Cards & Digital Banking', None, None, 'What is the USD to EGP exchange rate today?'),
]


def api(*args):
    out = subprocess.run(['curl', '-sS', '-m', '900', *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def sql(query):
    out = subprocess.run(['docker', 'exec', '-i', 'zakerly_postgres', 'psql', '-U', 'zakerly_user', '-d', 'zakerly_db',
                          '-v', 'ON_ERROR_STOP=1', '-tA'], input=query, capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stderr)
    return out.stdout.strip()


def q(text):
    return "'" + text.replace("'", "''") + "'"


def user_id(email):
    uid = sql(f'SELECT id FROM users WHERE email = {q(email)};')
    if not uid:
        sys.exit(f'No user with email {email}: sign up in the app first')
    return uid


def clear_book_cache():
    subprocess.run(['docker', 'exec', 'zakerly_redis', 'sh', '-c', "redis-cli --scan --pattern 'book*' | xargs -r redis-cli del"],
                   capture_output=True)


def load(owner):
    uid = user_id(owner)
    existing = set(sql('SELECT name FROM curriculum;').splitlines())
    for kb in MANIFEST:
        if kb['kb'] in existing:
            print(f"skip: knowledge base '{kb['kb']}' already exists (run `make demo-reset` to reload)")
            continue
        c = api('-X', 'POST', f'{API}/curriculums', '-H', 'Content-Type: application/json',
                '-d', json.dumps({'name': kb['kb'], 'description': kb['desc'], 'created_by': uid}))
        print(f"{kb['kb']}  (id {c['id']})", flush=True)
        for doc in kb['files']:
            started = time.time()
            path = HERE / 'documents' / doc['file']
            r = api('-X', 'POST', f"{API}/upload?curriculum_id={c['id']}",
                    '-F', f"file=@{path};type={MIME[path.suffix[1:]]}")
            if 'id' not in r:
                print(f"   FAILED {doc['file']}: {r}")
                continue
            # Readable title, also stored with each chunk so answers cite it
            sql(f"""UPDATE books SET title = {q(doc['title'])} WHERE id = {r['id']};
                    UPDATE "{embedding_table(kb['kb'])}" SET metadata = jsonb_set(metadata, '{{book_title}}', to_jsonb({q(doc['title'])}::text))
                    WHERE book_id = {r['id']};""")
            print(f"   {time.time() - started:5.1f}s  {doc['title']}", flush=True)
        sql(f"UPDATE curriculum SET created_by = {q(uid)} WHERE id = {c['id']};")
    clear_book_cache()


def embedding_table(kb_name):
    return sql(f'SELECT get_curriculum_embedding_table_name({q(kb_name)});')


def test(owner):
    uid = user_id(owner)
    ids = {b['title']: b['id'] for b in api(f'{API}/books')}
    sessions, failures = {}, 0
    for kb, doc, topic, question in QUESTIONS:
        if kb not in sessions:
            sessions[kb] = api('-X', 'POST', f"{API}/sessions?user_id={uid}&curriculum_name={urllib.parse.quote(kb)}"
                                             f"&session_name={urllib.parse.quote('Ask ' + kb)}")['id']
        started = time.time()
        r = api('-X', 'POST', f'{API}/chat', '-H', 'Content-Type: application/json', '-d', json.dumps(
            {'curriculum': kb, 'session_id': sessions[kb], 'user_message': question, 'book_id': ids.get(doc), 'topic': topic}))
        sources = r.get('metadata', {}).get('sources', [])
        cited = ', '.join(f"{s['document']}" + (f" p.{s['page']}" if s.get('page') else '') for s in sources[:3])
        ok = bool(sources) or 'exchange rate' in question
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {time.time() - started:4.0f}s  {question}\n      -> {cited or r['response'][:120]}", flush=True)
    sys.exit(1 if failures else 0)


def reset():
    names = ', '.join(q(kb['kb']) for kb in MANIFEST)
    rows = sql(f'SELECT id, name FROM curriculum WHERE name IN ({names});')
    if not rows:
        print('No demo knowledge bases found')
        return
    for row in rows.splitlines():
        kb_id, name = row.split('|', 1)
        sql(f"""BEGIN;
                DROP TABLE IF EXISTS "{embedding_table(name)}";
                DELETE FROM books WHERE curriculum_id = {kb_id};
                DELETE FROM curriculum WHERE id = {kb_id};
                COMMIT;""")
        print(f'deleted {name}')
    clear_book_cache()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', choices=['load', 'test', 'reset'])
    p.add_argument('--owner', help='email of the app user who owns the demo data / asks the test questions')
    a = p.parse_args()
    if a.command in ('load', 'test') and not a.owner:
        p.error(f'{a.command} needs --owner EMAIL')
    {'load': lambda: load(a.owner), 'test': lambda: test(a.owner), 'reset': reset}[a.command]()
