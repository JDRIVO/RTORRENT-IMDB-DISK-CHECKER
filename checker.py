import os
import logging
import time
from datetime import datetime
from threading import Thread
from remote_caller import SCGIRequest
from messenger import message
from deleter import Deleter

try:
	from importlib import reload
except:
	from imp import reload

try:
	import config as cfg
except Exception as e:
	logging.critical("checker.py: Config Error: Couldn't import config file: " + str(e) )

class Checker(SCGIRequest):

	def __init__(self, cache, checkerQueue, deleterQueue):
		super(Checker, self).__init__()
		self.cache = cache
		self.deletions = self.cache.deletions
		self.pending = self.cache.pending
		self.checkerQueue = checkerQueue
		self.deleter = Deleter(self.cache, deleterQueue)
		self.mountPoints = self.cache.mountPoints
		self.torrentsDownloading = self.cache.torrentsDownloading
		self.pendingDeletions = self.cache.pendingDeletions
		t = Thread(target=self.deletionHandler)
		t.start()

	def deletionHandler(self):

		while True:

			while self.deletions:
				self.pending.append(self.deletions[0][0])
				self.deleter.process(self.deletions.pop(0) )

			time.sleep(1)

	def check(self, torrentInfo):
		script, torrentName, torrentHash, torrentPath, torrentSize = torrentInfo
		torrentSize = int(torrentSize) / 1073741824.0

		try:
			reload(cfg)
		except Exception as e:
			self.cache.lock = False
			self.checkerQueue.release = True
			logging.critical("checker.py: {}: Config Error: Couldn't import config file: {}".format(torrentName, e) )
			return

		completedTorrents = self.cache.torrents
		completedTorrentsCopy = completedTorrents[:]
		parentDirectory = torrentPath.rsplit("/", 1)[0] if torrentName in torrentPath else torrentPath

		try:
			mountPoint = self.mountPoints[parentDirectory]
		except:
			mountPoint = [path for path in [parentDirectory.rsplit("/", num)[0] for num in range(parentDirectory.count("/") )] if os.path.ismount(path)]
			mountPoint = mountPoint[0] if mountPoint else "/"
			self.mountPoints[parentDirectory] = mountPoint

		try:
			downloads = self.torrentsDownloading[mountPoint]

			if downloads:

				try:
					downloading = self.send("d.multicall2", ('', "leeching", "d.left_bytes=", "d.hash=") )
					downloading = sum(tBytes for tBytes, tHash in downloading if tHash in downloads)
				except Exception as e:
					self.cache.lock = False
					self.checkerQueue.release = True
					logging.critical("checker.py: {}: XMLRPC Error: Couldn't retrieve torrents: {}".format(torrentName, e) )
					return

			else:
				downloading = 0

			downloads.append(torrentHash)

		except:
			self.torrentsDownloading[mountPoint] = [torrentHash]
			downloading = 0

		try:
			deletions = self.pendingDeletions[mountPoint]
		except:
			deletions = self.pendingDeletions[mountPoint] = 0

		disk = os.statvfs(mountPoint)
		availableSpace = (disk.f_bsize * disk.f_bavail + deletions - downloading) / 1073741824.0
		minimumSpace = cfg.minimum_space_mp[mountPoint] if mountPoint in cfg.minimum_space_mp else cfg.minimum_space
		requiredSpace = torrentSize - (availableSpace - minimumSpace)
		requirements = cfg.minimum_size, cfg.minimum_age, cfg.minimum_ratio, cfg.fallback_age, cfg.fallback_ratio

		include = override = True
		exclude = False
		freedSpace = 0
		fallbackTorrents = []
		currentDate = datetime.now()

		while freedSpace < requiredSpace:

			if not completedTorrentsCopy and not fallbackTorrents:
				break

			if completedTorrentsCopy:
				tAge, tLabel, tTracker, tRatio, tSizeBytes, tName, tHash, tPath, parentDirectory = completedTorrentsCopy[0]

				if override:
					override = False
					minSize, minAge, minRatio, fbAge, fbRatio = requirements

				if cfg.exclude_unlabelled and not tLabel:
					del completedTorrentsCopy[0]
					continue

				if cfg.labels:

					if tLabel in cfg.labels:
						labelRule = cfg.labels[tLabel]
						rule = labelRule[0]

						if rule is exclude:
							del completedTorrentsCopy[0]
							continue

						if rule is not include:
							override = True
							minSize, minAge, minRatio, fbAge, fbRatio = labelRule

					elif cfg.labels_only:
						del completedTorrentsCopy[0]
						continue

				if cfg.trackers and not override:
					trackerRule = [tracker for tracker in cfg.trackers for url in tTracker if tracker in url[0]]

					if trackerRule:
						trackerRule = cfg.trackers[trackerRule[0]]
						rule = trackerRule[0]

						if rule is exclude:
							del completedTorrentsCopy[0]
							continue

						if rule is not include:
							override = True
							minSize, minAge, minRatio, fbAge, fbRatio = trackerRule

					elif cfg.trackers_only:
						del completedTorrentsCopy[0]
						continue

				tAgeConverted = (currentDate - datetime.utcfromtimestamp(tAge) ).days
				tRatioConverted = tRatio / 1000.0
				tSizeGigabytes = tSizeBytes / 1073741824.0

				if tAgeConverted < minAge or tRatioConverted < minRatio or tSizeGigabytes < minSize:

						if fbAge is not False and tAgeConverted >= fbAge and tSizeGigabytes >= minSize:
							fallbackTorrents.append( (tAge, tLabel, tTracker, tRatio, tSizeBytes, tSizeGigabytes, tName, tHash, tPath, parentDirectory) )
						elif fbRatio is not False and tRatioConverted >= fbRatio and tSizeGigabytes >= minSize:
							fallbackTorrents.append( (tAge, tLabel, tTracker, tRatio, tSizeBytes, tSizeGigabytes, tName, tHash, tPath, parentDirectory) )

						del completedTorrentsCopy[0]
						continue

				del completedTorrentsCopy[0]

			else:
				tAge, tLabel, tTracker, tRatio, tSizeBytes, tSizeGigabytes, tName, tHash, tPath, parentDirectory = fallbackTorrents.pop(0)

			if self.mountPoints[parentDirectory] != mountPoint:
				continue

			try:
				self.send("d.open", (tHash,) )
			except:
				continue

			self.pendingDeletions[mountPoint] += tSizeBytes
			self.deletions.append( (tHash, tSizeBytes, tPath, mountPoint) )
			completedTorrents.remove([tAge, tLabel, tTracker, tRatio, tSizeBytes, tName, tHash, tPath, parentDirectory])
			freedSpace += tSizeGigabytes

		self.cache.lock = False
		self.checkerQueue.release = True

		if freedSpace >= requiredSpace:

			try:
				self.send("d.start", (torrentHash,) )
			except Exception as e:
				logging.error("checker.py: {}: XMLRPC Error: Couldn't start torrent: {}".format(torrentName, e) )
				return

		if freedSpace < requiredSpace and (cfg.enable_email or cfg.enable_pushbullet or cfg.enable_telegram or cfg.enable_slack):

			try:
				message()
			except Exception as e:
				logging.error("checker.py: Message Error: Couldn't send message: " + str(e) )
				return