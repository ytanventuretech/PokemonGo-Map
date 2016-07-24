#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys
import getpass
import argparse
import re
import uuid
import os
import json
from datetime import datetime, timedelta
import smtplib
import httplib2
import simplejson as json

from . import config
from exceptions import APIKeyException


def parse_unicode(bytestring):
    decoded_string = bytestring.decode(sys.getfilesystemencoding())
    return decoded_string


def get_args():
    # fuck PEP8
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--auth-service', type=str.lower, help='Auth Service', default='ptc')
    parser.add_argument('-u', '--username', help='Username', required=True)
    parser.add_argument('-p', '--password', help='Password', required=False)
    parser.add_argument('-l', '--location', type=parse_unicode, help='Location, can be an address or coordinates',
                        required=True)
    parser.add_argument('-st', '--step-limit', help='Steps', required=True, type=int)
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('-i', '--ignore', help='Comma-separated list of Pokémon names or IDs to ignore')
    group.add_argument('-o', '--only', help='Comma-separated list of Pokémon names or IDs to search')
    parser.add_argument('-ar', '--auto-refresh', help='Enables an autorefresh that behaves the same as'
                                                      ' a page reload. Needs an integer value for the amount of seconds')
    parser.add_argument('-dp', '--display-pokestops', help='Display pokéstops', action='store_true', default=False)
    parser.add_argument('-dl', '--display-lured', help='Display only lured pokéstop', action='store_true',
                        default=False)
    parser.add_argument('-dg', '--display-gyms', help='Display gyms', action='store_true', default=False)
    parser.add_argument('-H', '--host', help='Set web server listening host', default='127.0.0.1')
    parser.add_argument('-P', '--port', type=int, help='Set web server listening port', default=5000)
    parser.add_argument('-L', '--locale', help='Locale for Pokemon names: default en, check'
                                               'locale folder for more options', default='en')
    parser.add_argument('-c', '--china', help='Coordinates transformer for China', action='store_true')
    parser.add_argument('-d', '--debug', help='Debug Mode', action='store_true')
    parser.add_argument('-m', '--mock', help='Mock mode. Starts the web server but not the background thread.',
                        action='store_true', default=False)
    parser.add_argument('-k', '--google-maps-key', help='Google Maps Javascript API Key', default=None,
                        dest='gmaps_key')
    parser.add_argument('-pf', '--profile',
                        help='Set the profile, include emails to notify and interested Pokemons to to load',
                        default='profile.json')
    parser.set_defaults(DEBUG=False)
    args = parser.parse_args()
    if args.password is None:
        args.password = getpass.getpass()

    return args


def insert_mock_data(location, num_pokemons):
    from .models import Pokemon
    from .search import generate_location_steps

    prog = re.compile("^(\-?\d+\.\d+)?,\s*(\-?\d+\.\d+?)$")
    res = prog.match(location)
    latitude, longitude = float(res.group(1)), float(res.group(2))

    locations = [l for l in generate_location_steps((latitude, longitude), num_pokemons)]
    disappear_time = datetime.now() + timedelta(hours=1)

    for i in xrange(num_pokemons):
        Pokemon.create(encounter_id=uuid.uuid4(),
                       spawnpoint_id='sp{}'.format(i),
                       pokemon_id=(i + 1) % 150,
                       latitude=locations[i][0],
                       longitude=locations[i][1],
                       disappear_time=disappear_time)


def get_pokemon_name(pokemon_id):
    if not hasattr(get_pokemon_name, 'names'):
        file_path = os.path.join(
            config['ROOT_PATH'],
            config['LOCALES_DIR'],
            'pokemon.{}.json'.format(config['LOCALE']))

        with open(file_path, 'r') as f:
            get_pokemon_name.names = json.loads(f.read())

    return get_pokemon_name.names[str(pokemon_id)]


def load_credentials(filepath):
    with open(filepath + '/credentials.json') as file:
        creds = json.load(file)
        if not creds['gmaps_key']:
            raise APIKeyException( \
                'No Google Maps Javascript API key entered. Please take a look at the wiki for instructions on how to generate this key.')
        return creds


def load_profile():
    filename = 'profile.json'
    if get_args().profile:
        filename = get_args().profile
    file_path = os.path.dirname(os.path.realpath('runserver.py')) + '/' + filename

    with open(file_path) as f:
        profile = json.loads(f.read())

        if not profile['emails']:
            raise ImportError('No notification emails in profile.json.')
        else:
            email_to = profile['emails']

        if not profile['interested_pokemons']:
            raise ImportError('No interested Pokenmon IDs specified in profile.json.')
        else:
            interested = profile['interested_pokemons']
        return email_to, interested


def send_email(username, password, email_to, message):
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.ehlo()
    server.starttls()
    server.login(username, password)
    server.sendmail(username, email_to, message.encode('utf-8').strip())
    server.quit()

def shurl(longUrl):
    API_KEY = 'AIzaSyDIledAeDEV0TytxRu9UkCEILIOlmrhiL0'
    try:
        API_KEY
    except NameError:
        apiUrl = 'https://www.googleapis.com/urlshortener/v1/url'
    else:
        apiUrl = 'https://www.googleapis.com/urlshortener/v1/url?key=%s' % API_KEY

    headers = {"Content-type": "application/json"}
    data = {"longUrl": longUrl}
    h = httplib2.Http('.cache')
    try:
        headers, response = h.request(apiUrl, "POST", json.dumps(data), headers)
        short_url = json.loads(response)['id']

    except Exception, e:
        print "unexpected error %s" % e
    return short_url