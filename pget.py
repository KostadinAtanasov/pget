#!/usr/bin/env python

###############################################################################
# pget.py
#
# Copyright (C) 2013 Kostadin Atanasov <kdatanasov@gmail.com>
#
# This file is part of pget.
#
# pget is free software: you can redistribute it and/or modify
# if under the terms of GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pget is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should received a copy of the GNU General Public License
# along with pget. If not, see <http://www.gnu.org/licenses/>.
###############################################################################

import os
import time
import argparse
import configparser

from xml.etree import ElementTree as etree
from email.utils import parsedate
import urllib.request as request

###############################################################################
# Feed handling
###############################################################################

# Expected format for feeds:
#<rss xmlns:media="medians">
    #<channel>
        #<item>
        #   <title>Title</title>
        #   <description>Description</description>
        #   <pubDate>Date of Publication</pubDate>
        #   <guid isPermalink="false">GUID</guid>
        #   <media:content url="videourl" filesize="size" type="video/mp4" />
        #</item>
        #<item>
        #...
        #</item>
        #...
    #</channel>
#</rss>

class FeedItem:
    def __init__(self, title, descr, pubdate, guid, url, mtype):
        self.title = title
        self.descr = descr
        self.pubdate = pubdate
        self.guid = guid
        self.url = url
        self.mtype = mtype

    def shoulddownload(self, fname, path):
        return not os.path.exists(os.path.join(path, fname))

    def download(self, path, verbose=False, tell=False):
        cwd = os.getcwd()
        resp = None
        try:
            fn = self.url.split('/')[-1]
            fname = os.path.join(path, fn)
            if not self.shoulddownload(fn, path):
                if verbose:
                    print('%s already downloaded' % fn)
                return
            os.chdir(path)
            if verbose:
                print('Starting download of %s' % self.title)
            resp = request.urlopen(self.url)
            if resp.code != 200:
                msg = str(resp.code) + ' is currently unsupported'
                raise Exception(msg)
            length = float(resp.getheader('Content-Length'))
            chunksize = 32 * 1024
            totalsize = 0.0
            tmpfname = os.path.join(path, fn + '.downloading')
            downloaded = False
            with open(tmpfname, 'wb') as f:
                count = 0
                tstamp = 0.0
                while True:
                    if verbose and (count == 0):
                        tstamp = time.time()
                    chunk = resp.read(chunksize)
                    if not chunk:
                        break
                    totalsize += float(len(chunk))
                    count += 1
                    if verbose and (count == 32):
                        t = (time.time() - tstamp) / 32.0
                        perc = round((totalsize / length) * 100.0, 2)
                        rtime = (length - totalsize) / float(chunksize)
                        rtime = round((t * rtime / 60.0), 1)
                        print('downloaded %s%%\trem time %s min' % (perc, rtime))
                        count = 0
                    f.write(chunk)
                if totalsize == length:
                    os.rename(tmpfname, fname)
                    if tell:
                        print('%s downloaded' % fn)
        except Exception as e:
            print('[pget] Error downloading %s' % self.title)
            print('[pget]\t%s' % str(e))
        finally:
            if resp is not None: resp.close()
            os.chdir(cwd)

class Feed:
    def __init__(self, url, dpath, ddir, days):
        self.url = url

        self.dpath = dpath
        self.ddir = ddir
        self.days = days

        self.xml = None
        self.items = []

    def getnewer(self):
        secs = float(self.days) * 24 * 60 * 60
        treshold = time.time() - secs
        return [f for f in self.items if time.mktime(parsedate(f.pubdate)) > treshold]

    def poll(self):
        self.pollxml()
        if self.xml is not None: self.parsexml()

    def pollxml(self):
        try:
            resp = request.urlopen(self.url)
            self.xml = resp.read()
        except Exception as e:
            print('[pget] Error polling feed for %s' % self.url)
            print('[pget]\t%s' % str(e))

    def getxmlrootandnamespaces(self):
        from io import StringIO
        events = ['start', 'start-ns', 'end-ns']
        root = None
        nsmap = []
        xml = self.xml.decode('utf-8')
        for event, elem in etree.iterparse(StringIO(xml), events):
            if event == 'start-ns':
                nsmap.append(elem)
            elif event == 'start':
                if root is None:
                    root = elem
        return etree.ElementTree(root), dict(nsmap)

    def parsexml(self):
        root, nsmap = self.getxmlrootandnamespaces()
        if root is None:
            return
        channel = root.find('channel')
        if channel is None:
            return
        items = channel.findall('item')
        if items is None:
            return
        for item in items:
            title = item.find('title')
            if title is not None:
                title = title.text
            else:
                title = self.url + '(Unknown Title)'
            descr = item.find('description')
            if descr is not None:
                descr = descr.text
            else:
                descr = ''
            pubdate = item.find('pubDate')
            if pubdate is not None:
                pubdate = pubdate.text
            else:
                pubdate = 'Thu, 01 Jan 1970 02:00:00'
            guid = item.find('guid')
            if guid is not None:
                guid = guid.text
            else:
                guid = None
            medians = ''
            if 'media' in nsmap: # Seems obligatory to have it
                medians = nsmap['media']
            media = item.find('{%s}content' % medians)
            url = None
            if media is not None:
                url = media.get('url')
                mtype = media.get('type')
                self.items.append(FeedItem(title, descr, pubdate,
                                  guid, url, mtype))

        # Now that all items are in place sort them by date
        fis = sorted(self.items, key=lambda x: parsedate(x.pubdate))
        self.items = fis[::-1]

###############################################################################
# Application handling
###############################################################################
CONFDIR = os.environ['HOME'] + '/.config/pget'
CONFFILE = CONFDIR + '/pget.ini'
PODCASTFILE = CONFDIR + '/podcasts.ini'

class App:
    def __init__(self):
        self.args = None

        self.configfile = CONFFILE
        self.config = None

        self.podcastfile = PODCASTFILE
        self.pconfig = None

    def parsecmd(self):
        if self.args is not None:
            return # Already parsed
        parser = argparse.ArgumentParser('pget')
        parser.add_argument('-i', '--inifile',
                            help='read configuration defined in inifile')
        parser.add_argument('-p', '--podcastfile',
                            help='read RSSs links defined in podcastfile')
        datehelp = 'date(%%d/%%m/%%Y) only newer files will be downloaded'
        parser.add_argument('-d', '--date', help=datehelp)
        rmhelp = 'remove files older than given days(0 remove all)'
        parser.add_argument('-r', '--rmolder', type=int, help=rmhelp)
        parser.add_argument('-s', '--stall', action='store_true',
                            help='clear interrupted downloads')
        parser.add_argument('-v', '--verbose', action='store_true',
                            help='be verbose')
        parser.add_argument('-t', '--tell', action='store_true',
                            help='tell when each download finished')
        self.args = parser.parse_args()
        if self.args.podcastfile is not None:
            self.podcastfile = self.args.podcastfile
        if self.args.inifile is not None:
            self.configfile = self.args.inifile

    def loadconfig(self):
        if self.config is not None:
            return # Already loaded, should explicitly reaload it
        #self.config = configparser.ConfigParser()
        self.pconfig = configparser.ConfigParser()
        self.pconfig.read(self.podcastfile)

    def handlefeed(self, feed):
        if self.args.stall:
            # TODO: remove all files with download extension
            print('remove partially downloaded files - not implemented')
        if self.args.rmolder is not None:
            # TODO: get guids from CONFDIR/media and delete them
            print('rmolder - not implemented')
        else:
            newer = feed.getnewer()
            # Create download dir if not exists
            if not os.path.isdir(feed.dpath):
                os.mkdir(feed.dpath)
            fulldir = os.path.join(feed.dpath, feed.ddir)
            if not os.path.isdir(fulldir):
                os.mkdir(fulldir)
            if len(newer) > 0:
                for f in newer:
                    f.download(fulldir, self.args.verbose, self.args.tell)

if __name__ == '__main__':
    app = App()
    app.parsecmd()
    app.loadconfig()
    for secstr in app.pconfig.sections():
        sec = app.pconfig[secstr]
        valid = 'title' in sec and 'url' in sec
        valid = valid and 'dpath' in sec and 'dir' in sec
        if valid:
            feed = Feed(sec['url'], sec['dpath'], sec['dir'], sec['days'])
            feed.poll()
            app.handlefeed(feed)
