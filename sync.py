#!/usr/bin/env python3
"""Keeps the cloud poster (this repo, posted by GitHub Actions) in step with Resonance Creator.

  python3 sync.py      (the Mac's launchd job runs this every 15 min through "prepquest memes sync.app"; harmless offline)

Creator is the truth: what goes up, and when, is what Creator shows for Instagram.
 - your mark in Creator wins over the post file (Skipped or Posted there = the cloud never posts it)
 - your time in Creator (state.json "planned") wins over the post file's post_at
 - a post file already "scheduled" on Instagram (the old Business Suite queue) isn't the cloud's to post

1. pull: posts the cloud has published -> "posted" with the Reel link in Creator's post file (Creator shows it as Live)
2. push: memes Creator still needs on Instagram -> copied here with their video and time; ones you skipped or moved
   are updated or removed, so the cloud only ever posts what Creator says
3. nudge: if something is due now, start the cloud run at once (GitHub's own timer runs only every few hours)
"""
import json, glob, os, shutil, subprocess, datetime as dt

REPO = os.path.dirname(os.path.abspath(__file__))
CREATOR = os.path.expanduser('~/Desktop/Claude/marketing/posts')
STATE = os.path.expanduser('~/Library/Application Support/ResonanceCreator/state.json')
GH = shutil.which('gh') or '/opt/homebrew/bin/gh'
FMT = '%Y-%m-%d %H:%M'


def git(*a, check=True):
    return subprocess.run(['git', '-C', REPO, *a], capture_output=True, text=True, check=check)


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, d):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def ig_status(d):
    return (d.get('status') or {}).get('instagram') if isinstance(d.get('status'), dict) else None


def wanted(c, pid, state):
    """The Instagram time (post_at format) if the cloud should post this Creator post, else None."""
    if c.get('kind', 'content') != 'meme':                    # content videos go to @prepquest.org, not this account
        return None
    if 'instagram' not in c.get('platforms', ['instagram']) or not c.get('video') or not os.path.exists(c['video']):
        return None
    if ig_status(c) in ('posted', 'scheduled'):
        return None
    if (state.get('status', {}).get(pid) or {}).get('instagram') in ('posted', 'skipped'):
        return None
    planned = state.get('planned', {}).get(pid)
    return dt.datetime.fromtimestamp(planned).strftime(FMT) if planned else c.get('post_at')


def main():
    # This copy is only a mirror: everything here is rebuilt from Creator each run, so start from the cloud's exact state
    # (a crash or a clash last time can never leave it stuck).
    if git('fetch', '--quiet', 'origin', check=False).returncode != 0:
        print('offline; try later'); return
    git('rebase', '--abort', check=False)
    git('reset', '--hard', '--quiet', 'origin/main')
    state = load(STATE) if os.path.exists(STATE) else {}
    cloud = {os.path.basename(f)[:-5]: f for f in glob.glob(os.path.join(REPO, 'posts', '*.json'))}

    # 1. pull posted statuses back into Creator
    for pid, f in cloud.items():
        r = load(f)
        if ig_status(r) != 'posted':
            continue
        cf = os.path.join(CREATOR, pid + '.json')
        if os.path.exists(cf):
            c = load(cf)
            if ig_status(c) != 'posted':
                if not isinstance(c.get('status'), dict):
                    c['status'] = {}
                c['status']['instagram'] = 'posted'; c['ig'] = r.get('ig', {})
                save(cf, c); print('posted:', pid)
        v = os.path.join(REPO, r.get('video', ''))                # the video isn't needed in the cloud any more
        if r.get('video') and os.path.exists(v):
            git('rm', '-q', '--cached', r['video'], check=False); os.remove(v)

    # 2. push what Creator still needs, at Creator's time; drop what it no longer wants
    keep = set()
    for cf in glob.glob(os.path.join(CREATOR, '*.json')):
        pid = os.path.basename(cf)[:-5]
        c = load(cf)
        when = wanted(c, pid, state)
        if not when:
            continue
        rf = os.path.join(REPO, 'posts', pid + '.json')
        if os.path.exists(rf) and ig_status(load(rf)) == 'posted':
            continue
        keep.add(pid)
        vname = 'videos/' + os.path.basename(c['video'])
        if not os.path.exists(os.path.join(REPO, vname)):
            shutil.copy2(c['video'], os.path.join(REPO, vname))
        r = {k: c[k] for k in ('id', 'title', 'platforms', 'captions', 'status') if k in c}
        r['platforms'] = c.get('platforms', ['instagram'])
        r['post_at'] = when
        r['video'] = vname
        if not os.path.exists(rf) or load(rf) != r:
            save(rf, r)
    for pid, f in cloud.items():
        r = load(f)
        if pid not in keep and ig_status(r) != 'posted':     # skipped, marked posted by hand, or deleted in Creator
            git('rm', '-q', '-f', '--ignore-unmatch', f, r.get('video', '-'), check=False)
            for p in (f, os.path.join(REPO, r.get('video', '-'))):
                if os.path.exists(p):
                    os.remove(p)
            print('removed:', pid)

    git('add', '-A')
    if git('diff', '--cached', '--quiet', check=False).returncode != 0:
        git('commit', '-q', '-m', 'sync ' + dt.datetime.now().strftime(FMT))
        p = git('push', '-q', check=False)
        print('pushed' if p.returncode == 0 else 'push failed: ' + p.stderr[:200])

    # 3. something due now: post it now instead of waiting hours for GitHub's timer
    now = dt.datetime.now()
    due = [pid for pid in keep if dt.datetime.strptime(load(os.path.join(REPO, 'posts', pid + '.json'))['post_at'], FMT) <= now]
    if due:
        running = subprocess.run([GH, 'run', 'list', '-R', 'dpaortiz/prepquest-memes-poster', '-L', '1', '--json', 'status',
                                  '-q', '.[0].status'], capture_output=True, text=True).stdout.strip()
        if running not in ('queued', 'in_progress'):
            subprocess.run([GH, 'workflow', 'run', '-R', 'dpaortiz/prepquest-memes-poster', 'post due memes'], capture_output=True)
            print('started a cloud run for', len(due), 'due')


if __name__ == '__main__':
    os.nice(10)
    main()
