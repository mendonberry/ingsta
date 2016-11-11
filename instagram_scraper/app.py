#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Usage:
python app.py <username>
"""
import argparse
import errno
import json
import os
import re
import time
import traceback
import warnings

import concurrent.futures
import requests
import tqdm

from instagram_scraper.constants import *

warnings.filterwarnings('ignore')

class InstagramScraper(object):

    """InstagramScraper scrapes and downloads an instagram user's photos and videos"""

    def __init__(self, username, login_user=None, login_pass=None, dst=None, quiet=False):
        self.username = username
        self.login_user = login_user
        self.login_pass = login_pass

        if dst is not None:
            self.dst = dst
        else:
            self.dst = './' + self.username

        try:
            os.makedirs(self.dst)
        except OSError as err:
            if err.errno == errno.EEXIST and os.path.isdir(self.dst):
                # Directory already exists
                pass
            else:
                # Target dir exists as a file, or a different error
                raise

        # Controls the graphical output of tqdm
        self.quiet = quiet

        self.session = requests.Session()
        self.cookies = None
        self.logged_in = False

        if self.login_user and self.login_pass:
            self.login()

    def login(self):
        """Logs in to instagram"""
        self.session.headers.update({'Referer': BASE_URL})
        req = self.session.get(BASE_URL)

        self.session.headers.update({'X-CSRFToken': req.cookies['csrftoken']})

        login_data = {'username': self.login_user, 'password': self.login_pass}
        login = self.session.post(LOGIN_URL, data=login_data, allow_redirects=True)
        self.session.headers.update({'X-CSRFToken': login.cookies['csrftoken']})
        self.cookies = login.cookies

        if login.status_code == 200 and json.loads(login.text)['authenticated']:
            self.logged_in = True
        else:
            raise ValueError('Login failed for {0}'.format(self.login_user))

    def logout(self):
        """Logs out of instagram"""
        if self.logged_in:
            try:
                logout_data = {'csrfmiddlewaretoken': self.cookies['csrftoken']}
                self.session.post(LOGOUT_URL, data=logout_data)
                self.logged_in = False
            except requests.exceptions.RequestException:
                traceback.print_exc()

    def scrape(self):
        """Crawls through and downloads user's media"""
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        future_to_item = {}

        # Get the user metadata.
        user = self.fetch_user()

        if user:
            # Download the profile pic if not the default.
            if '11906329_960233084022564_1448528159' not in user['profile_pic_url_hd']:
                item = {'url': re.sub(r'/s\d{3,}x\d{3,}/', '/', user['profile_pic_url_hd'])}
                future = executor.submit(self.download, item, self.dst)
                future_to_item[future] = item

            if self.logged_in:
                # Get the user's stories.
                stories = self.fetch_stories(user['id'])

                # Downloads the user's stories and sends it to the executor.
                for item in tqdm.tqdm(stories, desc='Searching for stories', unit=" media", disable=self.quiet):
                    future = executor.submit(self.download, item, self.dst)
                    future_to_item[future] = item

        # Crawls the media and sends it to the executor.
        for item in tqdm.tqdm(self.media_gen(), desc='Searching for posts', unit=' media', disable=self.quiet):
            future = executor.submit(self.download, item, self.dst)
            future_to_item[future] = item

        # Displays the progress bar of completed downloads. Might not even pop up if all media is downloaded while
        # the above loop finishes.
        for future in tqdm.tqdm(concurrent.futures.as_completed(future_to_item), total=len(future_to_item),
                                desc='Downloading', disable=self.quiet):
            item = future_to_item[future]

            if future.exception() is not None:
                print('{0} generated an exception: {1}'.format(item['id'], future.exception()))

        self.logout()

    def fetch_user(self):
        """Fetches the user's metadata"""
        resp = self.session.get(BASE_URL + self.username)

        if resp.status_code == 200 and '_sharedData' in resp.text:
            shared_data = resp.text.split("window._sharedData = ")[1].split(";</script>")[0]
            return json.loads(shared_data)['entry_data']['ProfilePage'][0]['user']

    def fetch_stories(self, user_id):
        """Fetches the user's stories"""
        resp = self.session.get(STORIES_URL.format(user_id), headers={
            'user-agent' : STORIES_UA,
            'cookie'     : STORIES_COOKIE.format(self.cookies['ds_user_id'], self.cookies['sessionid'])
        })

        retval = json.loads(resp.text)

        if resp.status_code == 200 and 'items' in retval and len(retval['items']) > 0:
            return [self.set_story_url(item) for item in retval['items']]
        return []

    def media_gen(self):
        """Generator of all user's media"""
        media = self.fetch_media_json(max_id=None)

        while True:
            for item in media['items']:
                yield item
            if media.get('more_available'):
                max_id = media['items'][-1]['id']
                media = self.fetch_media_json(max_id)
            else:
                return

    def fetch_media_json(self, max_id):
        """Fetches the user's media metadata"""
        url = MEDIA_URL.format(self.username)

        if max_id is not None:
            url += '?&max_id=' + max_id

        resp = self.session.get(url)

        if resp.status_code == 200:
            media = json.loads(resp.text)

            if not media['items']:
                self.logout()
                raise ValueError('User {0} is private'.format(self.username))

            media['items'] = [self.set_media_url(item) for item in media['items']]
            return media
        else:
            self.logout()
            raise ValueError('User {0} does not exist'.format(self.username))

    def set_media_url(self, item):
        """Sets the media url"""
        item['url'] = item[item['type'] + 's']['standard_resolution']['url'].split('?')[0]
        # remove dimensions to get largest image
        item['url'] = re.sub(r'/s\d{3,}x\d{3,}/', '/', item['url'])
        return item

    def set_story_url(self, item):
        """Sets the story url"""
        item['url'] = item['image_versions2']['candidates'][0]['url'].split('?')[0]
        return item

    def download(self, item, save_dir='./'):
        """Downloads the media file"""
        base_name = item['url'].split('/')[-1]
        file_path = os.path.join(save_dir, base_name)

        if not os.path.isfile(file_path):
            with open(file_path, 'wb') as file:
                try:
                    content = self.session.get(item['url']).content
                except requests.exceptions.ConnectionError:
                    time.sleep(5)
                    content = requests.get(item['url']).content

                file.write(content)

            file_time = int(item.get('created_time', item.get('taken_at', time.time())))
            os.utime(file_path, (file_time, file_time))

def main():
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
    scraper.scrape()

if __name__ == '__main__':
    main()

