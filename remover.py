# -*- coding: utf-8 -*-

import sys, os, cacher, time
from torrents import completed
from remotecaller import xmlrpc

queue = sys.argv[1]
torrent_hash = sys.argv[2]
torrent_path = sys.argv[3]

t_hash = tuple([torrent_hash])
xmlrpc('d.tracker_announce', t_hash)
files = xmlrpc('f.multicall', (torrent_hash, '', 'f.frozen_path='))
xmlrpc('d.erase', t_hash)

with open(queue, 'a+') as txt:
        txt.write(torrent_hash + '\n')

time.sleep(0.001)

while True:

        try:
                with open(queue, 'r') as txt:
                        queued = txt.read().strip().splitlines()

                if queued[0] == torrent_hash:
                        break

                if torrent_hash not in queued:

                        with open(queue, 'a') as txt:
                                txt.write(torrent_hash + '\n')
        except:
                pass

        time.sleep(0.01)

if len(files) <= 1:
        os.remove(files[0][0])
else:
        [os.remove(file[0]) for file in files]

        try:
                os.rmdir(torrent_path)
        except:

                for root, directories, files in os.walk(torrent_path, topdown=False):

                        try:
                                os.rmdir(root)
                        except:
                                pass

txt = open(queue, mode='r+')
queued = txt.read().strip().splitlines()
txt.seek(0)
[txt.write(torrent + '\n') for torrent in queued if torrent != torrent_hash]
txt.truncate()
time.sleep(1)

try:
        queued = open(queue).read()

        if not queued:
                os.remove(queue)
                cacher.build_cache(torrent_hash)
except:
        pass
