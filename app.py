#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Usage: 
python app.py <username>
"""
import concurrent.futures
import json
import os
import requests
import sys
from tqdm import tqdm

class InstagramScraper:

    def __init__(self, username):
        self.username = username
        self.numPosts = 0
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self.future_to_item = {}

    def crawl(self, max_id=None):
        """Walks through the user's media"""
        url = 'http://instagram.com/' + self.username + '/media' + ('?&max_id=' + max_id if max_id is not None else '')
        resp = requests.get(url)
        media = json.loads(resp.text)

        self.numPosts += len(media['items'])

        for item in media['items']:
            future = self.executor.submit(self.download, item, './' + self.username)
            self.future_to_item[future] = item

        sys.stdout.write('\rFound %i post(s)' % self.numPosts)
        sys.stdout.flush()

        if 'more_available' in media and media['more_available'] is True:
            max_id = media['items'][-1]['id']
            self.crawl(max_id)

    def download(self, item, save_dir='./'):
        """Downloads the media file"""
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        item['url'] = item[item['type'] + 's']['standard_resolution']['url']
        base_name = item['url'].split('/')[-1].split('?')[0]
        file_path = os.path.join(save_dir, base_name)

        with open(file_path, 'wb') as file:
            bytes = requests.get(item['url']).content
            file.write(bytes)

        file_time = int(item['created_time'])
        os.utime(file_path, (file_time, file_time))

if __name__ == '__main__':
    username = sys.argv[1]

    scraper = InstagramScraper(username)
    scraper.crawl()

    for future in tqdm(concurrent.futures.as_completed(scraper.future_to_item), total=len(scraper.future_to_item), desc='Downloading'):
        item = scraper.future_to_item[future]

        if future.exception() is not None:
            print ('%r generated an exception: %s') % (item['url'], future.exception())
