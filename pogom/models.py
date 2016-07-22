#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
from peewee import Model, SqliteDatabase, InsertQuery, IntegerField, \
    CharField, FloatField, BooleanField, DateTimeField
from datetime import datetime
from base64 import b64encode

from .utils import get_pokemon_name
from pogom.utils import get_args
from pogom.pgoapi.utilities import get_pos_by_name
import smtplib
from sys import argv
import httplib2
import simplejson as json

db = SqliteDatabase('pogom.db')
log = logging.getLogger(__name__)

interested_pokegroup = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '23', '24', '25', '26', '27', '28', '30', '31',
         '33', '34', '35', '36', '37', '38', '39', '40', '50', '51', '53', '57', '58', '59', '62',
         '63', '64', '65', '67', '68', '72', '73', '75', '76',
         '77', '78', '81', '82', '83', '84', '85', '87', '89', '91', '93', '94', '95',
         '100', '101', '103', '105', '106', '107', '108', '110', '111', '113', '114', '115', '117', '119', '122', '124',
         '125', '126', '127', '130', '131', '132', '137', '138', '139', '140', '141', '142', '143', '144',
         '145', '146', '147', '148', '149', '150', '151']
SENT = []
TXT_TO = ['3085391356@vtext.com',
          '4024692675@vtext.com'
          #,'4024176691@messaging.sprintpcs.com'
         ]
EMAIL_TO = ['yingtan81@gmail.com', 'zhmanthony@gmail.com', 'crocole@gmail.com', 'toddraychrisman@gmail.com', 'chengqian.ty@gmail.com']


class BaseModel(Model):
    class Meta:
        database = db


class Pokemon(BaseModel):
    IGNORE = None
    ONLY = None

    # We are base64 encoding the ids delivered by the api
    # because they are too big for sqlite to handle
    encounter_id = CharField(primary_key=True)
    spawnpoint_id = CharField()
    pokemon_id = IntegerField()
    latitude = FloatField()
    longitude = FloatField()
    disappear_time = DateTimeField()

    @classmethod
    def get_active(cls):
        query = (Pokemon
                 .select()
                 .where(Pokemon.disappear_time > datetime.now())
                 .dicts())

        pokemons = []
        for p in query:
            p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
            pokemon_name = p['pokemon_name'].lower()
            pokemon_id = str(p['pokemon_id'])
            if cls.IGNORE:
                if pokemon_name in cls.IGNORE or pokemon_id in cls.IGNORE:
                    continue
            if cls.ONLY:
                if pokemon_name not in cls.ONLY and pokemon_id not in cls.ONLY:
                    continue
            pokemons.append(p)
        return pokemons


class Pokestop(BaseModel):
    pokestop_id = CharField(primary_key=True)
    enabled = BooleanField()
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()
    lure_expiration = DateTimeField(null=True)


class Gym(BaseModel):
    UNCONTESTED = 0
    TEAM_MYSTIC = 1
    TEAM_VALOR = 2
    TEAM_INSTINCT = 3

    gym_id = CharField(primary_key=True)
    team_id = IntegerField()
    guard_pokemon_id = IntegerField()
    enabled = BooleanField()
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()


def parse_map(map_dict):
    pokemons = {}
    pokestops = {}
    gyms = {}

    cells = map_dict['responses']['GET_MAP_OBJECTS']['map_cells']
    for cell in cells:
        for p in cell.get('wild_pokemons', []):
            pokemons[p['encounter_id']] = {
                'encounter_id': b64encode(str(p['encounter_id'])),
                'spawnpoint_id': p['spawnpoint_id'],
                'pokemon_id': p['pokemon_data']['pokemon_id'],
                'latitude': p['latitude'],
                'longitude': p['longitude'],
                'disappear_time': datetime.fromtimestamp(
                    (p['last_modified_timestamp_ms'] +
                     p['time_till_hidden_ms']) / 1000.0)
            }

        for f in cell.get('forts', []):
            if f.get('type') == 1:  # Pokestops
                if 'lure_info' in f:
                    lure_expiration = datetime.fromtimestamp(
                        f['lure_info']['lure_expires_timestamp_ms'] / 1000.0)
                else:
                    lure_expiration = None

                pokestops[f['id']] = {
                    'pokestop_id': f['id'],
                    'enabled': f['enabled'],
                    'latitude': f['latitude'],
                    'longitude': f['longitude'],
                    'last_modified': datetime.fromtimestamp(
                        f['last_modified_timestamp_ms'] / 1000.0),
                    'lure_expiration': lure_expiration
                }

            else:  # Currently, there are only stops and gyms
                gyms[f['id']] = {
                    'gym_id': f['id'],
                    'team_id': f['owned_by_team'],
                    'guard_pokemon_id': f['guard_pokemon_id'],
                    'enabled': f['enabled'],
                    'latitude': f['latitude'],
                    'longitude': f['longitude'],
                    'last_modified': datetime.fromtimestamp(
                        f['last_modified_timestamp_ms'] / 1000.0),
                }

    if pokemons:
        log.info("Upserting {} pokemon".format(len(pokemons)))
        InsertQuery(Pokemon, rows=pokemons.values()).upsert().execute()
        args = get_args()
        position = get_pos_by_name(args.location)
        office = str(position[0]) + ',' + str(position[1])
        username = str(args.username)
        password = str(args.password)

        for p in pokemons.values():
            # log.info(p)
            p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
            pokemon_name = p['pokemon_name'].lower()
            pokemon_id = str(p['pokemon_id'])
            if pokemon_id in interested_pokegroup and p['encounter_id'] not in SENT:
                SENT.append(p['encounter_id'])
                to = 'PokemonFan'
                loc = str(p['latitude']) + ',' + str(p['longitude'])
                icon = 'http://media.pldh.net/pokexycons/' + pokemon_id.zfill(3) + '.png'
                pokeMsg = pokemon_name + ' will disappear at ' + p['disappear_time'].strftime('%X') + '\n'
                img_url = 'https://maps.googleapis.com/maps/api/staticmap' \
                      '?center=' + office + ')}' \
                      '&zoom=15&size=640x640&markers=icon:' \
                      + icon.encode('utf-8').strip() + '%7C' \
                      + loc + '&key=AIzaSyDn-kxyG5NrrpFSft95w30SWR3YETJ5xDU'

                short_url = shurl(img_url)
                url = ''
                if short_url:
                    url = short_url
                else:
                    url = img_url

                message = "\r\n".join([
                    "From: %s" % username,
                    "To: %s" % to,
                    "Subject: %s" % pokemon_name,
                    "",
                    pokeMsg + url
                ])

                log.info("Send TXT: " + message.encode('utf-8').strip())

                server = smtplib.SMTP("smtp.gmail.com", 587)
                server.ehlo()
                server.starttls()
                server.login(username, password)
                server.sendmail(username, EMAIL_TO, message.encode('utf-8').strip())
                # for to in TXT_TO:
                #     server.sendmail(username, to, message.encode('utf-8').strip())
                server.quit()

    # if pokestops:
    #    log.info("Upserting {} pokestops".format(len(pokestops)))
    #    InsertQuery(Pokestop, rows=pokestops.values()).upsert().execute()

    if gyms:
        log.info("Upserting {} gyms".format(len(gyms)))
        InsertQuery(Gym, rows=gyms.values()).upsert().execute()


def create_tables():
    db.connect()
    db.create_tables([Pokemon, Pokestop, Gym], safe=True)
    db.close()


def shurl(longUrl):
    API_KEY='AIzaSyDIledAeDEV0TytxRu9UkCEILIOlmrhiL0'
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