#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import time
from base64 import b64encode
from datetime import datetime, timedelta

from dateutil import tz
from peewee import SqliteDatabase, InsertQuery,\
                   IntegerField, CharField, DoubleField, BooleanField,\
                   DateTimeField, OperationalError
from playhouse.flask_utils import FlaskDB
from playhouse.pool import PooledMySQLDatabase
from playhouse.shortcuts import RetryOperationalError

from pogom.pgoapi.utilities import get_pos_by_name
from pogom.utils import get_args, load_profile, send_email, shurl
from . import config
from .customLog import printPokemon
from .transform import transform_from_wgs_to_gcj
from .utils import get_pokemon_name, get_pokemon_rarity, get_pokemon_types, send_to_webhook

POKE_GROUP = load_profile()[1]
EMAIL_TO = load_profile()[0]
SENT = []
position = get_pos_by_name(get_args().location)
map_center = str(position[0]) + ',' + str(position[1])
username = get_args().username
password = get_args().password
local_timezone = tz.tzlocal()
cdt_tz = tz.gettz('America/Chicago')

log = logging.getLogger(__name__)

args = get_args()
flaskDb = FlaskDB()


class MyRetryDB(RetryOperationalError, PooledMySQLDatabase):
    pass


def init_database(app):
    if args.db_type == 'mysql':
        db = MyRetryDB(
            args.db_name,
            user=args.db_user,
            password=args.db_pass,
            host=args.db_host,
            max_connections=args.db_max_connections,
            stale_timeout=300)
        log.info('Connecting to MySQL database on {}.'.format(args.db_host))
    else:
        db = SqliteDatabase(args.db)
        log.info('Connecting to local SQLLite database.')

    app.config['DATABASE'] = db
    flaskDb.init_app(app)

    return db


class BaseModel(flaskDb.Model):

    @classmethod
    def get_all(cls):
        results = [m for m in cls.select().dicts()]
        if args.china:
            for result in results:
                result['latitude'], result['longitude'] = \
                    transform_from_wgs_to_gcj(
                        result['latitude'], result['longitude'])
        return results


class Pokemon(BaseModel):
    # We are base64 encoding the ids delivered by the api
    # because they are too big for sqlite to handle
    encounter_id = CharField(primary_key=True, max_length=50)
    spawnpoint_id = CharField(index=True)
    pokemon_id = IntegerField(index=True)
    latitude = DoubleField()
    longitude = DoubleField()
    disappear_time = DateTimeField(index=True)

    class Meta:
        indexes = ((('latitude', 'longitude'), False),)

    @classmethod
    def get_active(cls, swLat, swLng, neLat, neLng):
        if swLat is None or swLng is None or neLat is None or neLng is None:
            query = (Pokemon
                     .select()
                     .where(Pokemon.disappear_time > datetime.utcnow())
                     .dicts())
        else:
            query = (Pokemon
                     .select()
                     .where((Pokemon.disappear_time > datetime.utcnow()) &
                            (Pokemon.latitude >= swLat) &
                            (Pokemon.longitude >= swLng) &
                            (Pokemon.latitude <= neLat) &
                            (Pokemon.longitude <= neLng))
                     .dicts())

        pokemons = []
        for p in query:
            p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
            p['pokemon_rarity'] = get_pokemon_rarity(p['pokemon_id'])
            p['pokemon_types'] = get_pokemon_types(p['pokemon_id'])
            if args.china:
                p['latitude'], p['longitude'] = \
                    transform_from_wgs_to_gcj(p['latitude'], p['longitude'])
            pokemons.append(p)

        return pokemons

    @classmethod
    def get_active_by_id(cls, ids, swLat, swLng, neLat, neLng):
        if swLat is None or swLng is None or neLat is None or neLng is None:
            query = (Pokemon
                     .select()
                     .where((Pokemon.pokemon_id << ids) &
                            (Pokemon.disappear_time > datetime.utcnow()))
                     .dicts())
        else:
            query = (Pokemon
                     .select()
                     .where((Pokemon.pokemon_id << ids) &
                            (Pokemon.disappear_time > datetime.utcnow()) &
                            (Pokemon.latitude >= swLat) &
                            (Pokemon.longitude >= swLng) &
                            (Pokemon.latitude <= neLat) &
                            (Pokemon.longitude <= neLng))
                     .dicts())

        pokemons = []
        for p in query:
            p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
            p['pokemon_rarity'] = get_pokemon_rarity(p['pokemon_id'])
            p['pokemon_types'] = get_pokemon_types(p['pokemon_id'])
            if args.china:
                p['latitude'], p['longitude'] = \
                    transform_from_wgs_to_gcj(p['latitude'], p['longitude'])
            pokemons.append(p)

        return pokemons


class Pokestop(BaseModel):
    pokestop_id = CharField(primary_key=True, max_length=50)
    enabled = BooleanField()
    latitude = DoubleField()
    longitude = DoubleField()
    last_modified = DateTimeField(index=True)
    lure_expiration = DateTimeField(null=True, index=True)
    active_pokemon_id = IntegerField(null=True)

    class Meta:
        indexes = ((('latitude', 'longitude'), False),)

    @classmethod
    def get_stops(cls, swLat, swLng, neLat, neLng):
        if swLat is None or swLng is None or neLat is None or neLng is None:
            query = (Pokestop
                     .select()
                     .dicts())
        else:
            query = (Pokestop
                     .select()
                     .where((Pokestop.latitude >= swLat) &
                            (Pokestop.longitude >= swLng) &
                            (Pokestop.latitude <= neLat) &
                            (Pokestop.longitude <= neLng))
                     .dicts())

        pokestops = []
        for p in query:
            if args.china:
                p['latitude'], p['longitude'] = \
                    transform_from_wgs_to_gcj(p['latitude'], p['longitude'])
            pokestops.append(p)

        return pokestops


class Gym(BaseModel):
    UNCONTESTED = 0
    TEAM_MYSTIC = 1
    TEAM_VALOR = 2
    TEAM_INSTINCT = 3

    gym_id = CharField(primary_key=True, max_length=50)
    team_id = IntegerField()
    guard_pokemon_id = IntegerField()
    gym_points = IntegerField()
    enabled = BooleanField()
    latitude = DoubleField()
    longitude = DoubleField()
    last_modified = DateTimeField(index=True)

    class Meta:
        indexes = ((('latitude', 'longitude'), False),)

    @classmethod
    def get_gyms(cls, swLat, swLng, neLat, neLng):
        if swLat is None or swLng is None or neLat is None or neLng is None:
            query = (Gym
                     .select()
                     .dicts())
        else:
            query = (Gym
                     .select()
                     .where((Gym.latitude >= swLat) &
                            (Gym.longitude >= swLng) &
                            (Gym.latitude <= neLat) &
                            (Gym.longitude <= neLng))
                     .dicts())

        gyms = []
        for g in query:
            gyms.append(g)

        return gyms


class ScannedLocation(BaseModel):
    scanned_id = CharField(primary_key=True, max_length=50)
    latitude = DoubleField()
    longitude = DoubleField()
    last_modified = DateTimeField(index=True)

    class Meta:
        indexes = ((('latitude', 'longitude'), False),)

    @classmethod
    def get_recent(cls, swLat, swLng, neLat, neLng):
        query = (ScannedLocation
                 .select()
                 .where((ScannedLocation.last_modified >=
                        (datetime.utcnow() - timedelta(minutes=15))) &
                        (ScannedLocation.latitude >= swLat) &
                        (ScannedLocation.longitude >= swLng) &
                        (ScannedLocation.latitude <= neLat) &
                        (ScannedLocation.longitude <= neLng))
                 .dicts())

        scans = []
        for s in query:
            scans.append(s)

        return scans


def parse_map(map_dict, iteration_num, step, step_location):
    pokemons = {}
    pokestops = {}
    gyms = {}
    scanned = {}

    cells = map_dict['responses']['GET_MAP_OBJECTS']['map_cells']
    for cell in cells:
        if config['parse_pokemon']:
            for p in cell.get('wild_pokemons', []):
                d_t = datetime.utcfromtimestamp(
                    (p['last_modified_timestamp_ms'] +
                     p['time_till_hidden_ms']) / 1000.0)
                printPokemon(p['pokemon_data']['pokemon_id'], p['latitude'],
                             p['longitude'], d_t)
                pokemons[p['encounter_id']] = {
                    'encounter_id': b64encode(str(p['encounter_id'])),
                    'spawnpoint_id': p['spawnpoint_id'],
                    'pokemon_id': p['pokemon_data']['pokemon_id'],
                    'latitude': p['latitude'],
                    'longitude': p['longitude'],
                    'disappear_time': d_t
                }

                webhook_data = {
                    'encounter_id': b64encode(str(p['encounter_id'])),
                    'spawnpoint_id': p['spawnpoint_id'],
                    'pokemon_id': p['pokemon_data']['pokemon_id'],
                    'latitude': p['latitude'],
                    'longitude': p['longitude'],
                    'disappear_time': time.mktime(d_t.timetuple()),
                    'last_modified_time': p['last_modified_timestamp_ms'],
                    'time_until_hidden_ms': p['time_till_hidden_ms']
                }

                send_to_webhook('pokemon', webhook_data)

        for f in cell.get('forts', []):
            if config['parse_pokestops'] and f.get('type') == 1:  # Pokestops
                    if 'lure_info' in f:
                        lure_expiration = datetime.utcfromtimestamp(
                            f['lure_info']['lure_expires_timestamp_ms'] / 1000.0)
                        active_pokemon_id = f['lure_info']['active_pokemon_id']
                    else:
                        lure_expiration, active_pokemon_id = None, None

                    pokestops[f['id']] = {
                        'pokestop_id': f['id'],
                        'enabled': f['enabled'],
                        'latitude': f['latitude'],
                        'longitude': f['longitude'],
                        'last_modified': datetime.utcfromtimestamp(
                            f['last_modified_timestamp_ms'] / 1000.0),
                        'lure_expiration': lure_expiration,
                        'active_pokemon_id': active_pokemon_id
                    }

            elif config['parse_gyms'] and f.get('type') is None:  # Currently, there are only stops and gyms
                    gyms[f['id']] = {
                        'gym_id': f['id'],
                        'team_id': f.get('owned_by_team', 0),
                        'guard_pokemon_id': f.get('guard_pokemon_id', 0),
                        'gym_points': f.get('gym_points', 0),
                        'enabled': f['enabled'],
                        'latitude': f['latitude'],
                        'longitude': f['longitude'],
                        'last_modified': datetime.utcfromtimestamp(
                            f['last_modified_timestamp_ms'] / 1000.0),
                    }

    pokemons_upserted = 0
    pokestops_upserted = 0
    gyms_upserted = 0

    if pokemons and config['parse_pokemon']:
        pokemons_upserted = len(pokemons)
        log.debug("Upserting {} pokemon".format(len(pokemons)))
        bulk_upsert(Pokemon, pokemons)

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
                    img_url2 = 'https://maps.googleapis.com/maps/api/staticmap' \
                               '?center=' + map_center + ')}' \
                                                         '&zoom=17&size=640x640&markers=icon:' \
                               + icon.encode('utf-8').strip() + '%7C' \
                               + loc + '&key=AIzaSyDn-kxyG5NrrpFSft95w30SWR3YETJ5xDU'

                    short_url = shurl(img_url)
                    short_url2 = shurl(img_url2)
                    if short_url:
                        url = short_url
                    else:
                        url = img_url
                    if short_url2:
                        url2 = short_url2
                    else:
                        url2 = img_url2

                    message = "\r\n".join([
                        "Content-Type: text/html; charset=\"utf-8\""
                        "From: %s" % username,
                        "To: %s" % 'PokemonFan',
                        "Subject: %s" % pokemon_name,
                        "",
                        "<html><body><p>" + short_msg + "</p>" + "<img src=\"" + url + "\" />\r\n"
                        + "<img src=\"" + url2 + "\" /></body></html>"
                    ])

                    log.info("Send TXT: " + message)
                    send_email(username, password, EMAIL_TO, message)

    if pokestops and config['parse_pokestops']:
        pokestops_upserted = len(pokestops)
        log.debug("Upserting {} pokestops".format(len(pokestops)))
        bulk_upsert(Pokestop, pokestops)

    if gyms and config['parse_gyms']:
        gyms_upserted = len(gyms)
        log.debug("Upserting {} gyms".format(len(gyms)))
        bulk_upsert(Gym, gyms)

    log.info("Upserted {} pokemon, {} pokestops, and {} gyms".format(
      pokemons_upserted,
      pokestops_upserted,
      gyms_upserted))

    scanned[0] = {
        'scanned_id': str(step_location[0])+','+str(step_location[1]),
        'latitude': step_location[0],
        'longitude': step_location[1],
        'last_modified': datetime.utcnow(),
    }

    bulk_upsert(ScannedLocation, scanned)



def bulk_upsert(cls, data):
    num_rows = len(data.values())
    i = 0
    step = 120

    flaskDb.connect_db()

    while i < num_rows:
        log.debug("Inserting items {} to {}".format(i, min(i+step, num_rows)))
        try:
            InsertQuery(cls, rows=data.values()[i:min(i+step, num_rows)]).upsert().execute()
        except OperationalError as e:
            log.warning("%s... Retrying", e)
            continue

        i+=step

    flaskDb.close_db(None)


def create_tables(db):
    db.connect()
    db.create_tables([Pokemon, Pokestop, Gym, ScannedLocation], safe=True)
    db.close()

def drop_tables(db):
    db.connect()
    db.drop_tables([Pokemon, Pokestop, Gym, ScannedLocation], safe=True)
    db.close()
