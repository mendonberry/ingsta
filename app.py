#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Usage: 
python app.py <username>
"""

import argparse
import concurrent.futures
import errno
import json
import os
import re
import requests
import sys
import tqdm
import traceback
import warnings
import time

warnings.filterwarnings('ignore')


class InstagramScraper:

    def __init__(self, username, login_user=None, login_pass=None, dst=None):
        self.base_url = 'https://www.instagram.com/'
        self.login_url = self.base_url + 'accounts/login/ajax/'
        self.logout_url = self.base_url + 'accounts/logout/'
        self.username = username
        self.login_user = login_user
        self.login_pass = login_pass
        self.media_url = self.base_url + self.username + '/media'

        self.numPosts = 0
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self.future_to_item = {}

        if dst is not None:
            self.dst = dst
        else:
            self.dst = './' + self.username

        try:
            os.makedirs(self.dst)
        except OSError, e:
            if e.errno == errno.EEXIST and os.path.isdir(self.dst):
                # Directory already exists
                pass
            else:
                # Target dir exists as a file, or a different error
                raise

        self.session = requests.Session()
        self.csrf_token = None
        self.logged_in = False

        if self.login_user and self.login_pass:
            self.login()

    def login(self):
        self.session.headers.update({'Referer': self.base_url})
        req = self.session.get(self.base_url)

        self.session.headers.update({'X-CSRFToken': req.cookies['csrftoken']})

        login_data = {'username': self.login_user, 'password': self.login_pass}
        login = self.session.post(self.login_url, data=login_data, allow_redirects=True)
        self.session.headers.update({'X-CSRFToken': login.cookies['csrftoken']})
        self.csrf_token = login.cookies['csrftoken']

        if login.status_code == 200 and json.loads(login.text)['authenticated']:
            self.logged_in = True
        else:
            raise ValueError('Login failed for %s' % self.login_user)

    def logout(self):
        if self.logged_in:
            try:
                logout_data = {'csrfmiddlewaretoken': self.csrf_token}
                self.session.post(self.logout_url, data=logout_data)
                self.logged_in = False
            except:
                traceback.print_exc()

    def crawl(self, max_id=None):
        """Crawls through the user's media"""

        media = self.get_media(max_id)

        self.numPosts += len(media['items'])
        sys.stdout.write('\rFound %i post(s)' % self.numPosts)
        sys.stdout.flush()

        for item in media['items']:
            future = self.executor.submit(self.download, item, self.dst)
            self.future_to_item[future] = item

        if 'more_available' in media and media['more_available']:
            max_id = media['items'][-1]['id']
            self.crawl(max_id)

    def get_media(self, max_id):
        """Gets the user's media metadata"""

        url = self.media_url

        if max_id is not None:
            url += '?&max_id=' + max_id

        resp = self.session.get(url)

        if resp.status_code == 200:
            media = json.loads(resp.text)

            if not media['items']:
                self.logout()
                raise ValueError('User %s is private' % self.username)

            return media
        else:
            self.logout()
            raise ValueError('User %s does not exist' % self.username)

    def download(self, item, save_dir='./'):
        """Downloads the media file"""

        item['url'] = item[item['type'] + 's']['standard_resolution']['url'].split('?')[0]
        # remove dimensions to get largest image
        item['url'] = re.sub(r'/s\d{3,}x\d{3,}/', '/', item['url'])

        base_name = item['url'].split('/')[-1]
        file_path = os.path.join(save_dir, base_name)

        if not os.path.isfile(file_path):
            with open(file_path, 'wb') as file:

                try:
                    bytes = self.session.get(item['url']).content
                except requests.exceptions.ConnectionError:
                    time.sleep(5)
                    bytes = requests.get(item['url']).content

                file.write(bytes)

            file_time = int(item['created_time'])
            os.utime(file_path, (file_time, file_time))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="instagram-scraper scrapes and downloads an instagram user's photos and videos.")

    parser.add_argument('username', help='Instagram user to scrape')
    parser.add_argument('--destination', '-d', help='Download destination')
    parser.add_argument('--login_user', '-u', help='Instagram login user')
    parser.add_argument('--login_pass', '-p', help='Instagram login password')

    args = parser.parse_args()

    if (args.login_user and args.login_pass is None) or (args.login_user is None and args.login_pass):
        parser.print_help()
        raise ValueError('Must provide login user AND password')

    scraper = InstagramScraper(args.username, args.login_user, args.login_pass, args.destination)
    scraper.crawl()

    for future in tqdm.tqdm(concurrent.futures.as_completed(scraper.future_to_item), total=len(scraper.future_to_item),
                            desc='Downloading'):
        item = scraper.future_to_item[future]

        if future.exception() is not None:
            print '%r generated an exception: %s' % (item['id'], future.exception())

    concurrent.futures.wait(list(scraper.future_to_item.keys()))
    scraper.logout()
