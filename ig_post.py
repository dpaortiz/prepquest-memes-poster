#!/usr/bin/env python3
"""Auto-post @prepquest.memes Reels to Instagram (Instagram API with Instagram Login). No browser, no Business Suite.

    python3 ig_post.py setup <ACCESS_TOKEN>   store the token (macOS Keychain) and check it's @prepquest.memes
    python3 ig_post.py check                  show the connected account and what's due
    python3 ig_post.py run                    publish posts that are due (earliest first, one at a time, 10am-10pm; GitHub Actions runs this)
    python3 ig_post.py post <post.json>       publish one post now

Posts are the Resonance Creator post files in ~/Desktop/Claude/marketing/posts (the memes account only). A post is due
when it lists "instagram", its instagram status isn't posted/scheduled, and its post_at time has passed. After
publishing, its status becomes posted (Creator shows it) and the Reel's link goes into "ig".
The token is a never-expiring Meta system-user token (Keychain, service prepquest-memes-ig); app: 'memes poster'
(developers.facebook.com, app 2315777732575541), business portfolio 'Prepquest Memes'.
"""
import datetime as dt, json, os, sys, time, glob, subprocess, urllib.parse, urllib.request

POSTS = os.environ.get('POSTS_DIR') or os.path.expanduser('~/Desktop/Claude/marketing/posts')   # the cloud copy sets POSTS_DIR
LOG = os.environ.get('LOG_FILE') or os.path.expanduser('~/Desktop/Claude/prepquest-memes/ig/ig_post.log')
SERVICE = 'prepquest-memes-ig'
API = 'https://graph.facebook.com/v21.0'      # the token is a Meta system-user token (never expires)
EXPECTED = 'prepquest.memes'


def log(*a):
    line = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(str(x) for x in a)
    print(line)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def kc_get(key):
    env = {'token': 'IG_TOKEN', 'user_id': 'IG_USER_ID', 'kind': 'IG_TOKEN_KIND'}.get(key)
    if env and os.environ.get(env):                       # GitHub Actions: secrets come in as env vars
        return os.environ[env]
    if os.environ.get('IG_TOKEN'):                        # in the cloud there is no Keychain
        return None
    r = subprocess.run(['security', 'find-generic-password', '-s', SERVICE, '-a', key, '-w'], capture_output=True, text=True)
    return r.stdout.strip() or None


def kc_set(key, val):
    subprocess.run(['security', 'add-generic-password', '-U', '-s', SERVICE, '-a', key, '-w', val], check=True)


def call(method, url, params=None, data=None, headers=None, timeout=120):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{e.code} {e.read().decode()[:400]}')


def token():
    t = kc_get('token')
    if not t:
        sys.exit('No token yet: run  python3 ig_post.py setup <ACCESS_TOKEN>')
    last = kc_get('refreshed')
    if kc_get('kind') != 'system_user' and (not last or time.time() - float(last) > 7 * 86400):          # long-lived tokens last 60 days: refresh weekly
        try:
            r = call('GET', 'https://graph.instagram.com/refresh_access_token', {'grant_type': 'ig_refresh_token', 'access_token': t})
            if r.get('access_token'):
                t = r['access_token']; kc_set('token', t); kc_set('refreshed', str(time.time())); log('token refreshed')
        except Exception as e:
            log('token refresh failed:', e)
    return t


def me(t):
    return call('GET', f"{API}/{kc_get('user_id')}", {'fields': 'id,username', 'access_token': t})


def due_posts():
    now = dt.datetime.now()
    out = []
    for f in sorted(glob.glob(os.path.join(POSTS, '*.json'))):
        d = json.load(open(f))
        st = (d.get('status') or {}).get('instagram')
        if 'instagram' not in d.get('platforms', ['instagram']) or st in ('posted', 'scheduled') or not d.get('post_at') or not d.get('video'):
            continue
        try:
            when = dt.datetime.strptime(d['post_at'], '%Y-%m-%d %H:%M')     # New York time (TZ set in the workflow)
        except ValueError:
            log('SKIPPED bad post_at', os.path.basename(f), d['post_at']); continue
        if when <= now:
            out.append((d['post_at'], f))
    return [f for _, f in sorted(out)]                                  # earliest time first, not file name


def posts_allowed():
    """1 or 0: only in waking hours (10am-10:30pm New York) and at least 60 min after the last post, so a late run never
    bursts a backlog or posts at night. The schedule is 6 a day at 11:30, 3, 4:30, 6:30, 8 and 9:30 (owner, 2026-11-13,
    after Instagram restricted the account for looking automated; the closest pair is 90 min apart, so one late post
    doesn't push back the next)."""
    now = dt.datetime.now()
    if not (10 <= now.hour < 22 or (now.hour == 22 and now.minute < 30)):
        return 0
    last = [json.load(open(f)).get('ig', {}).get('posted_at') for f in glob.glob(os.path.join(POSTS, '*.json'))]
    last = max((x for x in last if x), default=None)
    if not last:
        return 1
    return 1 if (now - dt.datetime.strptime(last, '%Y-%m-%d %H:%M')).total_seconds() >= 60 * 60 else 0


def publish(path, t, uid):
    d = json.load(open(path))
    video = d['video'] if os.path.isabs(d['video']) else os.path.join(POSTS, '..', d['video'])
    cap = (d.get('captions') or {}).get('instagram') or d.get('caption', '')
    size = os.path.getsize(video)
    # 1. a Reels container with a resumable upload slot
    c = call('POST', f'{API}/{uid}/media', {'media_type': 'REELS', 'upload_type': 'resumable', 'caption': cap,
                                             'share_to_feed': 'true', 'access_token': t})
    cid, uri = c['id'], c['uri']
    # 2. upload the file straight from this Mac
    with open(video, 'rb') as fh:
        body = fh.read()
    call('POST', uri, data=body, headers={'Authorization': f'OAuth {t}', 'offset': '0', 'file_size': str(size)}, timeout=600)
    # 3. wait for Instagram to process it
    for _ in range(60):
        s = call('GET', f'{API}/{cid}', {'fields': 'status_code,status', 'access_token': t})
        if s.get('status_code') == 'FINISHED':
            break
        if s.get('status_code') in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'processing failed: {s}')
        time.sleep(10)
    else:
        raise RuntimeError('processing timed out')
    # 4. publish
    p = call('POST', f'{API}/{uid}/media_publish', {'creation_id': cid, 'access_token': t})
    # It's live: mark it posted before anything else can fail, or the next run would post it again.
    mark(path, {'media_id': p['id'], 'permalink': '', 'posted_at': dt.datetime.now().strftime('%Y-%m-%d %H:%M')})
    try:
        link = call('GET', f"{API}/{p['id']}", {'fields': 'permalink', 'access_token': t}).get('permalink', '')
        mark(path, {**json.load(open(path))['ig'], 'permalink': link})
    except Exception as e:
        link = f'(no link yet: {e})'
    log('posted', os.path.basename(path), link)


def mark(path, ig):
    d = json.load(open(path))                                     # re-read: the sync may have edited it meanwhile
    if not isinstance(d.get('status'), dict):
        d['status'] = {}
    d['status']['instagram'] = 'posted'
    d['ig'] = ig
    tmp = path + '.tmp'
    json.dump(d, open(tmp, 'w'), indent=1, ensure_ascii=False); os.replace(tmp, path)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == 'setup':
        kc_set('token', a[1]); kc_set('refreshed', str(time.time()))
        m = me(a[1])
        print('connected:', '@' + m.get('username', '?'), '| user id', m.get('id'))
        if m.get('username') != EXPECTED:
            print(f'WARNING: this is not @{EXPECTED}. Only the memes account should be connected.')
        return
    t = token(); uid = kc_get('user_id')
    if a[0] == 'check':
        print('account: @' + me(t).get('username', '?'))
        print('due now:', [os.path.basename(f) for f in due_posts()])
    elif a[0] == 'run':
        # The workflow calls this every few minutes: at most one post per call.
        for f in due_posts()[:posts_allowed()]:
            try:
                publish(f, t, uid)
            except Exception as e:
                log('FAILED', os.path.basename(f), e)
                break                                               # blocked or failing: the rest would fail the same way
    elif a[0] == 'post':
        publish(os.path.abspath(a[1]), t, uid)


if __name__ == '__main__':
    os.nice(10)
    main()
