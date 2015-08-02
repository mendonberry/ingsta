#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Usage: 
python app.py <username>
"""
import json
import os
import requests
import sys
import concurrent.futures
import argparse
import datetime

def crawl(username, items=[], max_id=None):
    url   = 'http://instagram.com/' + username + '/media' + ('?&max_id=' + max_id if max_id is not None else '')
    media = json.loads(requests.get(url).text)

    items.extend( [ curr_item for curr_item in media['items'] ] )

    if 'more_available' not in media or media['more_available'] is False:
        return items
    else:
        max_id = media['items'][-1]['id']
        return crawl(username, items, max_id)

def download(item, save_dir='./'):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url = item[item['type'] + 's']['standard_resolution']['url']
    base_name = url.split('/')[-1]
    if args.prefix_created_time_format:
      base_name = datetime.datetime.fromtimestamp(
                      int(item['created_time'])
                  ).strftime(args.prefix_created_time_format) + base_name
    file_path = os.path.join(save_dir, base_name)

    with open(file_path, 'wb') as file:
        print 'Downloading ' + base_name
        bytes = requests.get(url).content
        file.write(bytes)

if __name__ == '__main__':
  parser = argparse.ArgumentParser(add_help=True)
  parser.add_argument('username')
  parser.add_argument('--prefix-created-time',
                      nargs='?',
                      const='%Y%m%dT%H%M%S_',
                      dest='prefix_created_time_format',
                      help='Prefix the media filename with the specified datetime format')
  parser.add_argument('args', nargs=argparse.REMAINDER)

  global args
  args = parser.parse_args()


  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    future_to_item = dict( (executor.submit(download, item, './' + args.username), item) for item in crawl(args.username) )
  
    for future in concurrent.futures.as_completed(future_to_item):
      item = future_to_item[future]
      url  = item[item['type'] + 's']['standard_resolution']['url']
      
      if future.exception() is not None:
        print '%r generated an exception: %s' % (url, future.exception())

