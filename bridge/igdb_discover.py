"""Optional Xbox 360 game metadata browsing through IGDB. No download actions."""
import json
from datetime import datetime, timezone
import os
import re
import time
from urllib import parse, request


class IGDB:
    def __init__(self, opener=request.urlopen):
        self.opener = opener
        self.token = None
        self.token_until = 0
        self.last_request = 0
        self.facets = None

    def credentials(self):
        client = os.environ.get('NEBULAH_IGDB_CLIENT_ID', '')
        secret = os.environ.get('NEBULAH_IGDB_CLIENT_SECRET', '')
        return client, secret

    def status(self, data):
        if data:
            raise ValueError('Discovery status takes no options.')
        client, secret = self.credentials()
        return {'configured': bool(client and secret), 'source': 'IGDB'}

    def _json(self, url, body, headers):
        req = request.Request(url, data=body, headers=headers, method='POST')
        with self.opener(req, timeout=10) as response:
            payload = response.read(512 * 1024 + 1)
        if len(payload) > 512 * 1024:
            raise ValueError('Game database response was too large.')
        return json.loads(payload)

    def _token(self, client, secret):
        if self.token and time.monotonic() < self.token_until:
            return self.token
        values = parse.urlencode({'client_id': client, 'client_secret': secret,
                                  'grant_type': 'client_credentials'}).encode('ascii')
        result = self._json('https://id.twitch.tv/oauth2/token', values,
                            {'Content-Type': 'application/x-www-form-urlencoded'})
        token, seconds = result.get('access_token'), result.get('expires_in')
        if not isinstance(token, str) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError('IGDB authentication failed. Check the local Twitch application credentials.')
        self.token, self.token_until = token, time.monotonic() + max(0, seconds - 60)
        return token

    def _query(self, endpoint, body):
        client, secret = self.credentials()
        if not client or not secret:
            raise ValueError('Set NEBULAH_IGDB_CLIENT_ID and NEBULAH_IGDB_CLIENT_SECRET on the bridge PC.')
        pause = 0.26 - (time.monotonic() - self.last_request)
        if pause > 0:
            time.sleep(pause)
        self.last_request = time.monotonic()
        return self._json('https://api.igdb.com/v4/' + endpoint, body.encode('utf-8'),
                          {'Client-ID': client, 'Authorization': 'Bearer ' + self._token(client, secret),
                           'Content-Type': 'text/plain'})

    def filters(self, data):
        if data:
            raise ValueError('Filter list takes no options.')
        if self.facets and self.facets[0] > time.monotonic():
            return self.facets[1]
        facets = {}
        for endpoint in ('genres', 'themes', 'game_modes', 'age_rating_categories'):
            fields = 'id,rating,organization.name' if endpoint == 'age_rating_categories' else 'id,name'
            raw = self._query(endpoint, f'fields {fields}; sort id asc; limit 200;')
            if not isinstance(raw, list):
                raise ValueError('IGDB filter list was unavailable.')
            if endpoint == 'age_rating_categories':
                facets[endpoint] = [
                    {'id': item['id'], 'name': (item['organization']['name'] + ' ' + item['rating'])[:80]}
                    for item in raw if isinstance(item, dict) and type(item.get('id')) is int
                    and isinstance(item.get('rating'), str) and isinstance(item.get('organization'), dict)
                    and isinstance(item['organization'].get('name'), str)]
            else:
                facets[endpoint] = [{'id': item['id'], 'name': item['name'][:80]} for item in raw
                                    if isinstance(item, dict) and type(item.get('id')) is int
                                    and isinstance(item.get('name'), str)]
        self.facets = (time.monotonic() + 12 * 3600, facets)
        return facets

    def suggest(self, data):
        if not isinstance(data, dict) or set(data) != {'kind', 'query'} or data['kind'] not in ('series', 'developer'):
            raise ValueError('Choose a series or developer search.')
        term = data['query']
        if not isinstance(term, str) or not re.fullmatch(r"[\w .:'-]{2,60}", term):
            raise ValueError('Enter 2–60 plain search characters.')
        endpoint = 'collections' if data['kind'] == 'series' else 'companies'
        scope = 'games.platforms = (12) & ' if data['kind'] == 'series' else ''
        raw = self._query(endpoint, f'fields id,name; where {scope}name ~ *"{term}"*; limit 12;')
        if not isinstance(raw, list):
            raise ValueError('IGDB suggestions were unavailable.')
        return {'items': [{'id':item['id'], 'name':item['name'][:100]} for item in raw
                          if isinstance(item, dict) and type(item.get('id')) is int
                          and isinstance(item.get('name'), str)]}

    def search(self, data):
        if not isinstance(data, dict) or set(data) != {'query', 'genre', 'theme', 'mode', 'age', 'series', 'developer', 'online_coop', 'local_coop', 'year_from', 'year_to', 'rating', 'offset'}:
            raise ValueError('Enter a search and supported filters.')
        term, offset = data['query'], data['offset']
        if not isinstance(term, str) or (term and not re.fullmatch(r"[\w .:'-]{2,60}", term)):
            raise ValueError('Search must be 2–60 plain characters.')
        if type(offset) is not int or not 0 <= offset <= 500:
            raise ValueError('Choose a valid result page.')
        where = ['platforms = (12)', 'game_type = (0,8,9,10,11)']
        for field, key in (('genres', 'genre'), ('themes', 'theme'), ('game_modes', 'mode'), ('age_ratings.rating_category', 'age'),
                           ('collections', 'series'), ('involved_companies.company', 'developer')):
            value = data[key]
            if type(value) is not int or not 0 <= value <= 100000:
                raise ValueError('Choose a valid game filter.')
            if value:
                where.append(f'{field} = ({value})')
        if data['developer']:
            where.append('involved_companies.developer = true')
        if type(data['online_coop']) is not bool or type(data['local_coop']) is not bool:
            raise ValueError('Choose valid co-op filters.')
        if data['online_coop']:
            where.append('multiplayer_modes.onlinecoop = true')
        if data['local_coop']:
            where.append('(multiplayer_modes.offlinecoop = true | multiplayer_modes.splitscreen = true)')
        start, end, rating = data['year_from'], data['year_to'], data['rating']
        if any(type(value) is not int for value in (start, end, rating)) or not 0 <= rating <= 100 or any(value and not 2000 <= value <= 2035 for value in (start, end)) or (start and end and start > end):
            raise ValueError('Choose valid release years and rating.')
        if start:
            where.append(f'first_release_date >= {int(datetime(start, 1, 1, tzinfo=timezone.utc).timestamp())}')
        if end:
            where.append(f'first_release_date < {int(datetime(end + 1, 1, 1, tzinfo=timezone.utc).timestamp())}')
        if rating:
            where.append(f'total_rating >= {rating}')
        body = ('fields id,name,summary,first_release_date,total_rating,cover.image_id,genres.name; '
                + (f'search "{term}"; ' if term else 'sort total_rating_count desc; ')
                + f'where {" & ".join(where)}; limit 20; offset {offset};')
        raw = self._query('games', body)
        if not isinstance(raw, list):
            raise ValueError('IGDB returned an unexpected result.')
        return {'items': [self._game(item) for item in raw if isinstance(item, dict)],
                'offset': offset, 'source': 'IGDB'}

    def detail(self, data):
        if not isinstance(data, dict) or set(data) != {'id'} or type(data['id']) is not int or not 0 < data['id'] < 2**31:
            raise ValueError('Choose a game from the results.')
        body = ('fields id,name,summary,storyline,first_release_date,total_rating,aggregated_rating,'
                'cover.image_id,genres.name,themes.name,game_modes.name,'
                'involved_companies.company.name,involved_companies.developer,'
                'involved_companies.publisher,collections.name,age_ratings.organization.name,'
                'age_ratings.rating_category.rating,multiplayer_modes.platform,'
                'multiplayer_modes.onlinecoop,multiplayer_modes.offlinecoop,'
                'multiplayer_modes.splitscreen; '
                f'where id = {data["id"]} & platforms = (12) & game_type = (0,8,9,10,11); limit 1;')
        raw = self._query('games', body)
        if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
            raise ValueError('That Xbox 360 game is no longer available from IGDB.')
        item = raw[0]
        result = self._game(item)
        result['storyline'] = str(item.get('storyline') or '')[:4000]
        for key in ('themes', 'game_modes'):
            result[key] = [str(value.get('name'))[:80] for value in item.get(key, [])
                           if isinstance(value, dict) and isinstance(value.get('name'), str)][:16]
        result['developers'] = [company['company']['name'][:100] for company in item.get('involved_companies', [])
                                if isinstance(company, dict) and company.get('developer') is True
                                and isinstance(company.get('company'), dict)
                                and isinstance(company['company'].get('name'), str)][:12]
        result['series'] = [value['name'][:80] for value in item.get('collections', [])
                            if isinstance(value, dict) and isinstance(value.get('name'), str)][:8]
        result['age_ratings'] = [(value['organization']['name'] + ' ' + value['rating_category']['rating'])[:80]
                                 for value in item.get('age_ratings', []) if isinstance(value, dict)
                                 and isinstance(value.get('organization'), dict)
                                 and isinstance(value.get('rating_category'), dict)
                                 and isinstance(value['organization'].get('name'), str)
                                 and isinstance(value['rating_category'].get('rating'), str)][:8]
        result['coop'] = {'online': any(value.get('onlinecoop') is True for value in item.get('multiplayer_modes', [])
                                          if isinstance(value, dict) and value.get('platform') == 12),
                          'local': any(value.get('offlinecoop') is True or value.get('splitscreen') is True
                                       for value in item.get('multiplayer_modes', [])
                                       if isinstance(value, dict) and value.get('platform') == 12)}
        result['source'] = 'IGDB'
        return result

    @staticmethod
    def _game(item):
        cover = item.get('cover') if isinstance(item.get('cover'), dict) else {}
        return {'id': item.get('id') if type(item.get('id')) is int else None,
                'name': str(item.get('name') or '')[:160],
                'summary': str(item.get('summary') or '')[:2000],
                'release': item.get('first_release_date') if type(item.get('first_release_date')) is int else None,
                'rating': item.get('total_rating') if type(item.get('total_rating')) in (int, float) else None,
                'cover_id': cover.get('image_id') if isinstance(cover.get('image_id'), str) and re.fullmatch(r'[A-Za-z0-9_]{1,64}', cover['image_id']) else None,
                'genres': [str(g.get('name'))[:80] for g in item.get('genres', []) if isinstance(g, dict) and isinstance(g.get('name'), str)][:8]}
