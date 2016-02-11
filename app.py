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


def crawl(username, items=[], max_id=None):
    """Walks through the user's media"""
    url = 'http://instagram.com/' + username + '/media' + ('?&max_id=' + max_id if max_id is not None else '')
    media = json.loads(requests.get(url).text)

    items.extend([curr_item for curr_item in media['items']])

    if 'more_available' not in media or media['more_available'] is False:
        return items
    else:
        max_id = media['items'][-1]['id']
        return crawl(username, items, max_id)


def download(item, save_dir='./'):
    """Downloads the media file"""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url = item[item['type'] + 's']['standard_resolution']['url']
    base_name = url.split('/')[-1].split('?')[0]
    file_path = os.path.join(save_dir, base_name)

    with open(file_path, 'wb') as file:
        bytes = requests.get(url).content
        file.write(bytes)


if __name__ == '__main__':
    username = sys.argv[1]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_item = {}
        for item in crawl(username):
            future = executor.submit(download, item, './' + username)
            future_to_item[future] = item

        for future in tqdm(concurrent.futures.as_completed(future_to_item), total=len(future_to_item), desc='Downloading'):
            item = future_to_item[future]
            url = item[item['type'] + 's']['standard_resolution']['url']

            if future.exception() is not None:
                print ('%r generated an exception: %s') % (url, future.exception())
