BASE_URL = 'https://www.instagram.com/'
LOGIN_URL = BASE_URL + 'accounts/login/ajax/'
LOGOUT_URL = BASE_URL + 'accounts/logout/'
MEDIA_URL = BASE_URL + '{0}/media'

STORIES_URL = 'https://i.instagram.com/api/v1/feed/user/{0}/reel_media/'
STORIES_UA = 'Instagram 9.5.2 (iPhone7,2; iPhone OS 9_3_3; en_US; en-US; scale=2.00; 750x1334) AppleWebKit/420+'
STORIES_COOKIE = 'ds_user_id={0}; sessionid={1};'

TAGS_URL = BASE_URL + 'explore/tags/{0}/?__a=1'
LOCATIONS_URL = BASE_URL + 'explore/locations/{0}/?__a=1'
QUERY_URL = BASE_URL + 'query/'
VIEW_MEDIA_URL = BASE_URL + 'p/{0}/?__a=1'

QUERY_HASHTAG = ' '.join("""
    ig_hashtag(%s) { 
        media.after(%s, 20) {
            nodes {
                id,
                code,
                date,
                caption,
                display_src,
                is_video
            },
            page_info
        }   
    }
    """.split())

QUERY_LOCATION = ' '.join("""
    ig_location(%s) {
        media.after(%s, 12) {
            count,
                nodes {
                    caption,
                    code,
                    comments {
                        count
                    },
                    comments_disabled,
                    date,
                    dimensions {
                        height,
                        width
                    },
                    display_src,
                    id,
                    is_video,
                    likes {
                        count
                    },
                    owner {
                        id
                    },
                    thumbnail_src,
                    video_views
                },
                page_info
        }
    }
    """.split())