#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
from peewee import Model, SqliteDatabase, InsertQuery, IntegerField, \
    CharField, FloatField, BooleanField, DateTimeField
from datetime import datetime
from base64 import b64encode
from .utils import get_pokemon_name
from pogom.utils import get_args, load_profile, send_email, shurl
from pogom.pgoapi.utilities import get_pos_by_name
from dateutil import tz

db = SqliteDatabase('pogom.db')
log = logging.getLogger(__name__)

POKE_GROUP = load_profile()[1]
EMAIL_TO = load_profile()[0]
SENT = []
position = get_pos_by_name(get_args().location)
map_center = str(position[0]) + ',' + str(position[1])
username = get_args().username
password = get_args().password
local_timezone = tz.tzlocal()
cdt_tz = tz.gettz('America/Chicago')


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

        if len(EMAIL_TO) > 0 and len(POKE_GROUP) > 0:
            for p in pokemons.values():
                # log.info(p)
                p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
                pokemon_name = p['pokemon_name'].lower()
                pokemon_id = str(p['pokemon_id'])

                if pokemon_id in POKE_GROUP and p['encounter_id'] not in SENT:
                    SENT.append(p['encounter_id'])

                    if len(SENT) > 10000:
                        del SENT[0:1000]

                    loc = str(p['latitude']) + ',' + str(p['longitude'])
                    icon = 'http://media.pldh.net/pokexycons/' + pokemon_id.zfill(3) + '.png'
                    disappear_time = p['disappear_time'].replace(tzinfo=local_timezone).astimezone(cdt_tz)
                    short_msg = pokemon_name + ' will disappear at ' + disappear_time.strftime('%X') + '\n'
                    img_url = 'https://maps.googleapis.com/maps/api/staticmap' \
                              '?center=' + map_center + ')}' \
                                                        '&zoom=15&size=640x640&markers=icon:' \
                              + icon.encode('utf-8').strip() + '%7C' \
                              + loc + '&key=AIzaSyDn-kxyG5NrrpFSft95w30SWR3YETJ5xDU'

                    short_url = shurl(img_url)
                    if short_url:
                        url = short_url
                    else:
                        url = img_url

                    message = "\r\n".join([
                        "From: %s" % username,
                        "To: %s" % 'PokemonFan',
                        "Subject: %s" % pokemon_name,
                        "",
                        short_msg + url
                    ])

                    log.info("Send TXT: " + message)
                    send_email(username, password, EMAIL_TO, message)


    # if pokestops:
    #    log.info("Upserting {} pokestops".format(len(pokestops)))
    #    InsertQuery(Pokestop, rows=pokestops.values()).upsert().execute()

    # if gyms:
    #     log.info("Upserting {} gyms".format(len(gyms)))
    #     InsertQuery(Gym, rows=gyms.values()).upsert().execute()


def create_tables():
    db.connect()
    db.create_tables([Pokemon, Pokestop, Gym], safe=True)
    db.close()
