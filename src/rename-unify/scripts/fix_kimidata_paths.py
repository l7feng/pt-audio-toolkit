# -*- coding: utf-8 -*-
"""修复 daimon-share 内的旧路径 D:\\KimiData\\ → D:\\Ai-Files\\Agent-Work\\KimiData\\"""
import os, shutil, time

ROOT = r'D:\Ai-Files\Agent-Work\KimiData\daimon-share'

OLD_WIN = r'D:\KimiData'          # 用于 .json / .cfg 里的双反斜杠转义形态
NEW_WIN = r'D:\Ai-Files\Agent-Work\KimiData'
OLD_POSIX = 'D:/KimiData'         # 用于 file:/// URI 里的正斜杠形态
NEW_POSIX = 'D:/Ai-Files/Agent-Work/KimiData'

TARGETS = [
    r'daimon\releases\release-pins.v2.json',
    r'daimon\runtime\python\.venv\pyvenv.cfg',
    r'daimon\skills\.daimon-managed-builtin-skills.json',
    r'daimon\provision.log',
]

for rel in TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print('  跳过（不存在）:', rel)
        continue
    with open(p, 'r', encoding='utf-8') as f:
        t = f.read()
    orig = t

    # JSON/config 里的双反斜杠转义形态：D:\\KimiData
    t = t.replace('D:\\\\KimiData', 'D:\\\\Ai-Files\\\\Agent-Work\\\\KimiData')
    # provision.log 里的正斜杠 file:/// 形态
    t = t.replace(OLD_POSIX, NEW_POSIX)

    if t == orig:
        print('  无需修改:', rel)
        continue

    bak = p + '.bak-%s' % time.strftime('%Y%m%d%H%M%S')
    shutil.copy2(p, bak)
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(t)
    print('  已修正: %s  （备份 %s）' % (rel, os.path.basename(bak)))

print()
print('=== 复核：是否还有残留旧路径 ===')
leftover = 0
for dp, dn, fn in os.walk(ROOT):
    if 'logs' in dp.split(os.sep):
        continue
    for f in fn:
        if f.endswith(('.bak', '.pyc')):
            continue
        p = os.path.join(dp, f)
        try:
            t = open(p, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        for i, ln in enumerate(t.splitlines(), 1):
            if 'KimiData' in ln and 'Ai-Files' not in ln and 'Ai-files' not in ln:
                print('  [残留] %s :%d  %s' % (os.path.relpath(p, ROOT), i, ln.strip()[:100]))
                leftover += 1
if leftover == 0:
    print('  (无残留，logs 目录除外)')
