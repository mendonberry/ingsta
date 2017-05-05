#!/usr/bin/python
# -*- coding: utf-8 -*-

import argparse
import codecs
import errno
import glob
import json
import logging.config
import os
import re
import time
import warnings

import concurrent.futures
import requests
import tqdm

from instagram_scraper.constants import *

warnings.filterwarnings('ignore')

class InstagramScraper(object):

    """InstagramScraper scrapes and downloads an instagram user's photos and videos"""
    def __init__(self, **kwargs):
        default_attr = dict(username='', usernames=[], filename=None,
                            login_user=None, login_pass=None,
                            destination='./', retain_username=False,
                            quiet=False, maximum=0, media_metadata=False, latest=False,
                            media_types=['image', 'video', 'story'], tag=False)

        allowed_attr = list(default_attr.keys())
        default_attr.update(kwargs)

        for key in default_attr:
            if key in allowed_attr:
                self.__dict__[key] = kwargs.get(key)

        # Set up a file logger
        self.logger = InstagramScraper.get_logger(level=logging.WARN)

        self.posts = []
        self.session = requests.Session()
        self.cookies = None
        self.logged_in = False
        self.last_scraped_filemtime = 0

    def login(self):
        """Logs in to instagram."""
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
            self.logger.exception('Login failed for ' + self.login_user)
            raise ValueError('Login failed for ' + self.login_user)

    def logout(self):
        """Logs out of instagram."""
        if self.logged_in:
            try:
                logout_data = {'csrfmiddlewaretoken': self.cookies['csrftoken']}
                self.session.post(LOGOUT_URL, data=logout_data)
                self.logged_in = False
            except requests.exceptions.RequestException:
                self.logger.warning('Failed to log out ' + self.login_user)

    def make_dst_dir(self, username):
        """Creates the destination directory."""
        if self.destination == './':
            dst = './' + username
        else:
            if self.retain_username:
                dst = self.destination + '/' + username
            else:
                dst = self.destination

        try:
            os.makedirs(dst)
        except OSError as err:
            if err.errno == errno.EEXIST and os.path.isdir(dst):
                # Directory already exists
                self.get_last_scraped_filemtime(dst)
                pass
            else:
                # Target dir exists as a file, or a different error
                raise

        return dst

    def get_last_scraped_filemtime(self, dst):
        """Stores the last modified time of newest file in a directory."""
        list_of_files = []
        file_types = ('*.jpg', '*.mp4')

        for type in file_types:
            list_of_files.extend(glob.glob(dst + '/' + type))

        if list_of_files:
            latest_file = max(list_of_files, key=os.path.getmtime)
            self.last_scraped_filemtime = int(os.path.getmtime(latest_file))

    def is_new_media(self, item):
        """Returns True if the media is new."""
        return self.latest is False or self.last_scraped_filemtime == 0 or \
               ('created_time' not in item and 'date' not in item) or \
               (int(item.get('created_time', item.get('date'))) > self.last_scraped_filemtime)

    def scrape_hashtag(self, executor=concurrent.futures.ThreadPoolExecutor(max_workers=10)):
        """Scrapes the specified hashtag for posted media."""
        for hashtag in self.usernames:
            self.posts = []
            self.last_scraped_filemtime = 0
            future_to_item = {}

            # Make the destination dir.
            dst = self.make_dst_dir(hashtag)

            iter = 0
            for item in tqdm.tqdm(self.hashtag_media_gen(hashtag), desc='Searching #{0} for posts'.format(hashtag), unit=" media",
                                  disable=self.quiet):
                future = executor.submit(self.download, item, dst)
                future_to_item[future] = item

                if self.media_metadata:
                    self.posts.append(item)

                iter = iter + 1
                if self.maximum != 0 and iter >= self.maximum:
                    break

            # Displays the progress bar of completed downloads. Might not even pop up if all media is downloaded while
            # the above loop finishes.
            for future in tqdm.tqdm(concurrent.futures.as_completed(future_to_item), total=len(future_to_item),
                                    desc='Downloading', disable=self.quiet):
                item = future_to_item[future]

                if future.exception() is not None:
                    self.logger.warning(
                        'Media for #{0} at {1} generated an exception: {2}'.format( hashtag, item['urls'], future.exception()))

            if self.media_metadata and self.posts:
                self.save_json(self.posts, '{0}/{1}.json'.format(dst, hashtag))

    def hashtag_media_gen(self, hashtag):
        """Generator for hashtag media."""
        resp = self.session.get(TAGS_URL.format(hashtag))

        if resp.status_code == 200:
            csrftoken = resp.cookies['csrftoken']
            tag = json.loads(resp.text)['tag']

            media = self.get_media_from_nodes(tag['media']['nodes'])
            end_cursor = tag['media']['page_info']['end_cursor']

            if media:
                try:
                    while True:
                        for item in media:
                            if (
                                (item['is_video'] is False and 'image' in self.media_types) or \
                                (item['is_video'] is True and 'video' in self.media_types)
                            ) and self.is_new_media(item):
                                yield item

                        if end_cursor:
                            media, end_cursor = self.query_hashtag(hashtag, end_cursor, csrftoken)
                        else:
                            return
                except ValueError:
                    self.logger.exception('Failed to query hashtag #' + hashtag)
            else:
                raise ValueError('No media found for hashtag #' + hashtag)

    def get_media_from_nodes(self, nodes):
        """Fetches the media urls."""
        for node in nodes:
            if node['is_video']:
                r = self.session.get(VIEW_MEDIA_URL.format(node['code']))
                if r.status_code == 200:
                    node['urls'] = [json.loads(r.text)['graphql']['shortcode_media']['video_url']]
                    self.extract_tags(node)
                else:
                    self.logger.warn('Failed to get video url for hashtag')
            else:
                node['urls'] = [self.get_original_image(node['display_src'])]
                self.extract_tags(node)
        return nodes

    def query_hashtag(self, tag, end_cursor, csrftoken):
        """Queries the hashtag using GraphQL."""
        form_data = {
            'q': QUERY_HASHTAG % (tag, end_cursor),
            'ref': 'tags::show',
        }

        headers = {
            'X-CSRFToken': csrftoken,
            'Referer': TAGS_URL.format(tag)
        }

        resp = self.session.post(QUERY_URL, data=form_data, headers=headers)

        if resp.status_code == 200:
            media = json.loads(resp.text)['media']
            nodes = media['nodes']
            return self.get_media_from_nodes(nodes), media['page_info']['end_cursor']

    def scrape(self, executor=concurrent.futures.ThreadPoolExecutor(max_workers=10)):
        """Crawls through and downloads user's media"""
        if self.login_user and self.login_pass:
            self.login()

        for username in self.usernames:
            self.posts = []
            self.last_scraped_filemtime = 0
            future_to_item = {}

            # Make the destination dir.
            dst = self.make_dst_dir(username)

            # Get the user metadata.
            user = self.fetch_user(username)

            if user:
                self.get_profile_pic(dst, executor, future_to_item, user, username)
                self.get_stories(dst, executor, future_to_item, user, username)

            # Crawls the media and sends it to the executor.
            self.get_media(dst, executor, future_to_item, username)

            # Displays the progress bar of completed downloads. Might not even pop up if all media is downloaded while
            # the above loop finishes.
            for future in tqdm.tqdm(concurrent.futures.as_completed(future_to_item), total=len(future_to_item),
                                    desc='Downloading', disable=self.quiet):
                item = future_to_item[future]

                if future.exception() is not None:
                    self.logger.warning(
                        'Media at {0} generated an exception: {1}'.format(item['urls'], future.exception()))

            if self.media_metadata and self.posts:
                self.save_json(self.posts, '{0}/{1}.json'.format(dst, username))

        self.logout()

    def get_profile_pic(self, dst, executor, future_to_item, user, username):
        # Download the profile pic if not the default.
        if 'image' in self.media_types and 'profile_pic_url_hd' in user \
                and '11906329_960233084022564_1448528159' not in user['profile_pic_url_hd']:
            item = {'urls': [re.sub(r'/s\d{3,}x\d{3,}/', '/', user['profile_pic_url_hd'])], 'created_time': 1286323200}

            if self.latest is False or os.path.isfile(dst + '/' + item['urls'][0].split('/')[-1]) is False:
                for item in tqdm.tqdm([item], desc='Searching {0} for profile pic'.format(username), unit=" images",
                                      ncols=0, disable=self.quiet):
                    future = executor.submit(self.download, item, dst)
                    future_to_item[future] = item

    def get_stories(self, dst, executor, future_to_item, user, username):
        """Scrapes the user's stories."""
        if self.logged_in and 'story' in self.media_types:
            # Get the user's stories.
            stories = self.fetch_stories(user['id'])

            # Downloads the user's stories and sends it to the executor.
            iter = 0
            for item in tqdm.tqdm(stories, desc='Searching {0} for stories'.format(username), unit=" media",
                                  disable=self.quiet):
                future = executor.submit(self.download, item, dst)
                future_to_item[future] = item

                iter = iter + 1
                if self.maximum != 0 and iter >= self.maximum:
                    break

    def get_media(self, dst, executor, future_to_item, username):
        """Scrapes the user's posts for media."""
        iter = 0
        for item in tqdm.tqdm(self.media_gen(username), desc='Searching {0} for posts'.format(username),
                              unit=' media', disable=self.quiet):
            future = executor.submit(self.download, item, dst)
            future_to_item[future] = item

            if self.media_metadata:
                self.posts.append(item)

            iter = iter + 1
            if self.maximum != 0 and iter >= self.maximum:
                break

    def fetch_user(self, username):
        """Fetches the user's metadata."""
        resp = self.session.get(BASE_URL + username)

        if resp.status_code == 200 and '_sharedData' in resp.text:
            try:
                shared_data = resp.text.split("window._sharedData = ")[1].split(";</script>")[0]
                return json.loads(shared_data)['entry_data']['ProfilePage'][0]['user']
            except (TypeError, KeyError, IndexError):
                pass

    def fetch_stories(self, user_id):
        """Fetches the user's stories."""
        resp = self.session.get(STORIES_URL.format(user_id), headers={
            'user-agent' : STORIES_UA,
            'cookie'     : STORIES_COOKIE.format(self.cookies['ds_user_id'], self.cookies['sessionid'])
        })

        retval = json.loads(resp.text)

        if resp.status_code == 200 and 'items' in retval and len(retval['items']) > 0:
            return [self.set_story_url(item) for item in retval['items']]
        return []

    def media_gen(self, username):
        """Generator of all user's media."""
        try:
            media = self.fetch_media_json(username, max_id=None)

            while True:
                for item in media['items']:
                    if self.in_media_types(item) and self.is_new_media(item):
                        yield item

                if media.get('more_available') and self.is_new_media(media['items'][-1]):
                    max_id = media['items'][-1]['id']
                    media = self.fetch_media_json(username, max_id)
                else:
                    return
        except ValueError:
            self.logger.exception('Failed to get media for ' + username)

    def fetch_media_json(self, username, max_id):
        """Fetches the user's media metadata."""
        url = MEDIA_URL.format(username)

        if max_id is not None:
            url += '?&max_id=' + max_id

        resp = self.session.get(url)

        if resp.status_code == 200:
            media = json.loads(resp.text)

            if not media['items']:
                raise ValueError('User {0} is private'.format(username))

            media['items'] = [self.augment_media_item(item) for item in media['items']]
            return media
        else:
            raise ValueError('User {0} does not exist'.format(username))

    def in_media_types(self, item):
        if item['type'] == 'carousel':
            for carousel_item in item['carousel_media']:
                if carousel_item['type'] in self.media_types:
                    return True
        else:
            return item['type'] in self.media_types

        return False

    def augment_media_item(self, item):
        """Augments media item object with new properties."""
        self.get_media_urls(item)
        self.extract_tags(item)
        return item

    def get_media_urls(self, item):
        """Sets the media url."""
        urls = []
        if item['type'] == 'carousel':
            for carousel_item in item['carousel_media']:
                url = carousel_item[carousel_item['type'] + 's']['standard_resolution']['url'].split('?')[0]
                urls.append(self.get_original_image(url))
        else:
            url = item[item['type'] + 's']['standard_resolution']['url'].split('?')[0]
            urls.append(self.get_original_image(url))

        item['urls'] = urls
        return item

    def extract_tags(self, item):
        """Extracts the hashtags from the caption text."""
        if 'caption' in item and item['caption']:
            if isinstance(item['caption'], dict):
                caption_text = item['caption']['text']
            else:
                caption_text = item['caption']
            # include words and emojis
            item['tags'] = re.findall(r"(?<!&)#(\w+|(?:[\xA9\xAE\u203C\u2049\u2122\u2139\u2194-\u2199\u21A9\u21AA\u231A\u231B\u2328\u2388\u23CF\u23E9-\u23F3\u23F8-\u23FA\u24C2\u25AA\u25AB\u25B6\u25C0\u25FB-\u25FE\u2600-\u2604\u260E\u2611\u2614\u2615\u2618\u261D\u2620\u2622\u2623\u2626\u262A\u262E\u262F\u2638-\u263A\u2648-\u2653\u2660\u2663\u2665\u2666\u2668\u267B\u267F\u2692-\u2694\u2696\u2697\u2699\u269B\u269C\u26A0\u26A1\u26AA\u26AB\u26B0\u26B1\u26BD\u26BE\u26C4\u26C5\u26C8\u26CE\u26CF\u26D1\u26D3\u26D4\u26E9\u26EA\u26F0-\u26F5\u26F7-\u26FA\u26FD\u2702\u2705\u2708-\u270D\u270F\u2712\u2714\u2716\u271D\u2721\u2728\u2733\u2734\u2744\u2747\u274C\u274E\u2753-\u2755\u2757\u2763\u2764\u2795-\u2797\u27A1\u27B0\u27BF\u2934\u2935\u2B05-\u2B07\u2B1B\u2B1C\u2B50\u2B55\u3030\u303D\u3297\u3299]|\uD83C[\uDC04\uDCCF\uDD70\uDD71\uDD7E\uDD7F\uDD8E\uDD91-\uDD9A\uDE01\uDE02\uDE1A\uDE2F\uDE32-\uDE3A\uDE50\uDE51\uDF00-\uDF21\uDF24-\uDF93\uDF96\uDF97\uDF99-\uDF9B\uDF9E-\uDFF0\uDFF3-\uDFF5\uDFF7-\uDFFF]|\uD83D[\uDC00-\uDCFD\uDCFF-\uDD3D\uDD49-\uDD4E\uDD50-\uDD67\uDD6F\uDD70\uDD73-\uDD79\uDD87\uDD8A-\uDD8D\uDD90\uDD95\uDD96\uDDA5\uDDA8\uDDB1\uDDB2\uDDBC\uDDC2-\uDDC4\uDDD1-\uDDD3\uDDDC-\uDDDE\uDDE1\uDDE3\uDDEF\uDDF3\uDDFA-\uDE4F\uDE80-\uDEC5\uDECB-\uDED0\uDEE0-\uDEE5\uDEE9\uDEEB\uDEEC\uDEF0\uDEF3]|\uD83E[\uDD10-\uDD18\uDD80-\uDD84\uDDC0]|(?:0\u20E3|1\u20E3|2\u20E3|3\u20E3|4\u20E3|5\u20E3|6\u20E3|7\u20E3|8\u20E3|9\u20E3|#\u20E3|\\*\u20E3|\uD83C(?:\uDDE6\uD83C(?:\uDDEB|\uDDFD|\uDDF1|\uDDF8|\uDDE9|\uDDF4|\uDDEE|\uDDF6|\uDDEC|\uDDF7|\uDDF2|\uDDFC|\uDDE8|\uDDFA|\uDDF9|\uDDFF|\uDDEA)|\uDDE7\uD83C(?:\uDDF8|\uDDED|\uDDE9|\uDDE7|\uDDFE|\uDDEA|\uDDFF|\uDDEF|\uDDF2|\uDDF9|\uDDF4|\uDDE6|\uDDFC|\uDDFB|\uDDF7|\uDDF3|\uDDEC|\uDDEB|\uDDEE|\uDDF6|\uDDF1)|\uDDE8\uD83C(?:\uDDF2|\uDDE6|\uDDFB|\uDDEB|\uDDF1|\uDDF3|\uDDFD|\uDDF5|\uDDE8|\uDDF4|\uDDEC|\uDDE9|\uDDF0|\uDDF7|\uDDEE|\uDDFA|\uDDFC|\uDDFE|\uDDFF|\uDDED)|\uDDE9\uD83C(?:\uDDFF|\uDDF0|\uDDEC|\uDDEF|\uDDF2|\uDDF4|\uDDEA)|\uDDEA\uD83C(?:\uDDE6|\uDDE8|\uDDEC|\uDDF7|\uDDEA|\uDDF9|\uDDFA|\uDDF8|\uDDED)|\uDDEB\uD83C(?:\uDDF0|\uDDF4|\uDDEF|\uDDEE|\uDDF7|\uDDF2)|\uDDEC\uD83C(?:\uDDF6|\uDDEB|\uDDE6|\uDDF2|\uDDEA|\uDDED|\uDDEE|\uDDF7|\uDDF1|\uDDE9|\uDDF5|\uDDFA|\uDDF9|\uDDEC|\uDDF3|\uDDFC|\uDDFE|\uDDF8|\uDDE7)|\uDDED\uD83C(?:\uDDF7|\uDDF9|\uDDF2|\uDDF3|\uDDF0|\uDDFA)|\uDDEE\uD83C(?:\uDDF4|\uDDE8|\uDDF8|\uDDF3|\uDDE9|\uDDF7|\uDDF6|\uDDEA|\uDDF2|\uDDF1|\uDDF9)|\uDDEF\uD83C(?:\uDDF2|\uDDF5|\uDDEA|\uDDF4)|\uDDF0\uD83C(?:\uDDED|\uDDFE|\uDDF2|\uDDFF|\uDDEA|\uDDEE|\uDDFC|\uDDEC|\uDDF5|\uDDF7|\uDDF3)|\uDDF1\uD83C(?:\uDDE6|\uDDFB|\uDDE7|\uDDF8|\uDDF7|\uDDFE|\uDDEE|\uDDF9|\uDDFA|\uDDF0|\uDDE8)|\uDDF2\uD83C(?:\uDDF4|\uDDF0|\uDDEC|\uDDFC|\uDDFE|\uDDFB|\uDDF1|\uDDF9|\uDDED|\uDDF6|\uDDF7|\uDDFA|\uDDFD|\uDDE9|\uDDE8|\uDDF3|\uDDEA|\uDDF8|\uDDE6|\uDDFF|\uDDF2|\uDDF5|\uDDEB)|\uDDF3\uD83C(?:\uDDE6|\uDDF7|\uDDF5|\uDDF1|\uDDE8|\uDDFF|\uDDEE|\uDDEA|\uDDEC|\uDDFA|\uDDEB|\uDDF4)|\uDDF4\uD83C\uDDF2|\uDDF5\uD83C(?:\uDDEB|\uDDF0|\uDDFC|\uDDF8|\uDDE6|\uDDEC|\uDDFE|\uDDEA|\uDDED|\uDDF3|\uDDF1|\uDDF9|\uDDF7|\uDDF2)|\uDDF6\uD83C\uDDE6|\uDDF7\uD83C(?:\uDDEA|\uDDF4|\uDDFA|\uDDFC|\uDDF8)|\uDDF8\uD83C(?:\uDDFB|\uDDF2|\uDDF9|\uDDE6|\uDDF3|\uDDE8|\uDDF1|\uDDEC|\uDDFD|\uDDF0|\uDDEE|\uDDE7|\uDDF4|\uDDF8|\uDDED|\uDDE9|\uDDF7|\uDDEF|\uDDFF|\uDDEA|\uDDFE)|\uDDF9\uD83C(?:\uDDE9|\uDDEB|\uDDFC|\uDDEF|\uDDFF|\uDDED|\uDDF1|\uDDEC|\uDDF0|\uDDF4|\uDDF9|\uDDE6|\uDDF3|\uDDF7|\uDDF2|\uDDE8|\uDDFB)|\uDDFA\uD83C(?:\uDDEC|\uDDE6|\uDDF8|\uDDFE|\uDDF2|\uDDFF)|\uDDFB\uD83C(?:\uDDEC|\uDDE8|\uDDEE|\uDDFA|\uDDE6|\uDDEA|\uDDF3)|\uDDFC\uD83C(?:\uDDF8|\uDDEB)|\uDDFD\uD83C\uDDF0|\uDDFE\uD83C(?:\uDDF9|\uDDEA)|\uDDFF\uD83C(?:\uDDE6|\uDDF2|\uDDFC))))[\ufe00-\ufe0f\u200d]?)+", caption_text, re.UNICODE)
        return item

    def get_original_image(self, url):
        """Gets the full-size image from the specified url."""
        # remove dimensions to get largest image
        url = re.sub(r'/s\d{3,}x\d{3,}/', '/', url)
        # get non-square image if one exists
        url = re.sub(r'/c\d{1,}.\d{1,}.\d{1,}.\d{1,}/', '/', url)
        return url

    def set_story_url(self, item):
        """Sets the story url."""
        item['urls'] = [item['image_versions2']['candidates'][0]['url'].split('?')[0]]
        return item

    def download(self, item, save_dir='./'):
        """Downloads the media file."""
        for url in item['urls']:
            base_name = url.split('/')[-1]
            file_path = os.path.join(save_dir, base_name)

            if not os.path.isfile(file_path):
                with open(file_path, 'wb') as media_file:
                    try:
                        content = self.session.get(url).content
                    except requests.exceptions.ConnectionError:
                        time.sleep(5)
                        content = requests.get(url).content

                    media_file.write(content)

                file_time = int(item.get('created_time', item.get('taken_at', item.get('date', time.time()))))
                os.utime(file_path, (file_time, file_time))

    @staticmethod
    def save_json(data, dst='./'):
        """Saves the data to a json file."""
        if data:
            with open(dst, 'wb') as f:
                json.dump(data, codecs.getwriter('utf-8')(f), indent=4, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def get_logger(level=logging.WARNING, log_file='instagram-scraper.log'):
        """Returns a file logger."""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.NOTSET)

        handler = logging.FileHandler(log_file, 'w')
        handler.setLevel(level)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        return logger

    @staticmethod
    def parse_file_usernames(usernames_file):
        """Parses a file containing a list of usernames."""
        users = []

        try:
            with open(usernames_file) as user_file:
                for line in user_file.readlines():
                    # Find all usernames delimited by ,; or whitespace
                    users += re.findall(r'[^,;\s]+', line)
        except IOError as err:
            raise ValueError('File not found ' + err)

        return users

    @staticmethod
    def parse_delimited_str(input):
        """Parse the string input as a list of delimited tokens."""
        return re.findall(r'[^,;\s]+', input)

def main():
    parser = argparse.ArgumentParser(
        description="instagram-scraper scrapes and downloads an instagram user's photos and videos.")

    parser.add_argument('username', help='Instagram user(s) to scrape', nargs='*')
    parser.add_argument('--destination', '-d', default='./', help='Download destination')
    parser.add_argument('--login_user', '-u', default=None, help='Instagram login user')
    parser.add_argument('--login_pass', '-p', default=None, help='Instagram login password')
    parser.add_argument('--filename', '-f', help='Path to a file containing a list of users to scrape')
    parser.add_argument('--quiet', '-q', default=False, action='store_true', help='Be quiet while scraping')
    parser.add_argument('--maximum', '-m', type=int, default=0, help='Maximum number of items to scrape')
    parser.add_argument('--retain_username', '-n', action='store_true', default=False,
                        help='Creates username subdirectory when destination flag is set')
    parser.add_argument('--media_metadata', action='store_true', default=False, help='Save media metadata to json file')
    parser.add_argument('--media_types', '-t', nargs='+', default=['image', 'video', 'story'], help='Specify media types to scrape')
    parser.add_argument('--latest', action='store_true', default=False, help='Scrape new media since the last scrape')
    parser.add_argument('--tag', action='store_true', default=False, help='Scrape media using a hashtag')

    args = parser.parse_args()

    if (args.login_user and args.login_pass is None) or (args.login_user is None and args.login_pass):
        parser.print_help()
        raise ValueError('Must provide login user AND password')

    if not args.username and args.filename is None:
        parser.print_help()
        raise ValueError('Must provide username(s) OR a file containing a list of username(s)')
    elif args.username and args.filename:
        parser.print_help()
        raise ValueError('Must provide only one of the following: username(s) OR a filename containing username(s)')

    if args.filename:
        args.usernames = InstagramScraper.parse_file_usernames(args.filename)
    else:
        args.usernames = InstagramScraper.parse_delimited_str(','.join(args.username))

    if args.media_types and len(args.media_types) == 1 and re.compile(r'[,;\s]+').findall(args.media_types[0]):
        args.media_types = InstagramScraper.parse_delimited_str(args.media_types[0])

    scraper = InstagramScraper(**vars(args))

    if args.tag:
        scraper.scrape_hashtag()
    else:
        scraper.scrape()

if __name__ == '__main__':
    main()
