#!/usr/bin/env python3
"""Keeps the cloud poster (this repo, posted by GitHub Actions every 15 min) in step with Resonance Creator.

  python3 sync.py      (the Mac's launchd job runs this every 15 min; harmless if offline)

1. pull: posts the cloud has published -> marked posted (with the Reel link) in Creator's post files
2. push: memes waiting for Instagram in Creator (post_at set, not posted) -> copied here with their video, then pushed,
   so the cloud can post them even when the Mac is closed. Times and captions edited in Creator are re-synced.
"""
import json, glob, os, shutil, subprocess, datetime as dt

REPO = os.path.dirname(os.path.abspath(__file__))
CREATOR = os.path.expanduser('~/Desktop/Claude/marketing/posts')


def git(*a, check=True):
    return subprocess.run(['git', '-C', REPO, *a], capture_output=True, text=True, check=check)


def main():
    if git('pull', '--rebase', '--quiet', check=False).returncode != 0:
        print('offline or pull failed; try later'); return
    # 1. pull posted statuses back into Creator
    for f in glob.glob(os.path.join(REPO, 'posts', '*.json')):
        r = json.load(open(f))
        if (r.get('status') or {}).get('instagram') != 'posted':
            continue
        cf = os.path.join(CREATOR, os.path.basename(f))
        if os.path.exists(cf):
            c = json.load(open(cf))
            if (c.get('status') or {}).get('instagram') != 'posted':
                if not isinstance(c.get('status'), dict):
                    c['status'] = {}
                c['status']['instagram'] = 'posted'; c['ig'] = r.get('ig', {})
                tmp = cf + '.tmp'; json.dump(c, open(tmp, 'w'), indent=1, ensure_ascii=False); os.replace(tmp, cf)
                print('posted:', os.path.basename(f))
        v = os.path.join(REPO, r.get('video', ''))                # the video isn't needed in the cloud any more
        if r.get('video') and os.path.exists(v):
            git('rm', '-q', '--cached', r['video'], check=False); os.remove(v)
    # 2. push what's waiting
    for cf in glob.glob(os.path.join(CREATOR, '*.json')):
        c = json.load(open(cf))
        st = (c.get('status') or {}).get('instagram')
        if 'instagram' not in c.get('platforms', []) or st in ('posted', 'scheduled') or not c.get('post_at') or not c.get('video'):
            continue
        if not os.path.exists(c['video']):
            continue
        rf = os.path.join(REPO, 'posts', os.path.basename(cf))
        if os.path.exists(rf) and (json.load(open(rf)).get('status') or {}).get('instagram') == 'posted':
            continue
        vname = 'videos/' + os.path.basename(c['video'])
        if not os.path.exists(os.path.join(REPO, vname)):
            shutil.copy2(c['video'], os.path.join(REPO, vname))
        r = {k: c[k] for k in ('id', 'title', 'post_at', 'platforms', 'captions', 'status') if k in c}
        r['video'] = vname
        old = json.load(open(rf)) if os.path.exists(rf) else None
        if old != r:
            json.dump(r, open(rf, 'w'), indent=1, ensure_ascii=False)
    git('add', '-A')
    if git('diff', '--cached', '--quiet', check=False).returncode != 0:
        git('commit', '-q', '-m', 'sync ' + dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
        p = git('push', '-q', check=False)
        print('pushed' if p.returncode == 0 else 'push failed: ' + p.stderr[:200])


if __name__ == '__main__':
    os.nice(10)
    main()
