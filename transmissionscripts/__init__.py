#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple script to clean out torrents that should no longer be tracked within
the client.
"""
import argparse
import errno
from json import dumps, load
from os.path import expanduser, join, exists, isdir
from os import makedirs
from transmissionrpc import Client
from transmissionrpc import DEFAULT_PORT

CONFIG_DIR = expanduser("~/.config/transmissionscripts")
CONFIG_FILE = join(CONFIG_DIR, "config.json")

REMOTE_MESSAGES = {
    "unregistered torrent"  # BTN / Gazelle
}

LOCAL_ERRORS = {
    "no data found"
}

# Seed a bit longer than required to account for any weirdness
SEED_TIME_BUFFER = 1.1


RULES_DEFAULT = 'DEFAULT'

CONFIG = {
    'CLIENT': {
        'host': 'localhost',
        'port': DEFAULT_PORT,
        'user': None,
        'password': None
    },
    'RULES': {
        'apollo.rip/': {
            'min_time': int((3600 * 24 * 30) * SEED_TIME_BUFFER),
            'max_ratio': 2.0
        },
        'landof.tv/': {
            'min_time': int((3600 * 120.0) * SEED_TIME_BUFFER),
            'max_ratio': 1.0
        },
        RULES_DEFAULT: {
            'min_time': int((3600 * 240) * SEED_TIME_BUFFER),
            'max_ratio': 2.0
        }
    }
}


def find_rule_set(trackers):
    for key in CONFIG['RULES']:
        for tracker in trackers:
            if key in tracker['announce'].lower():
                return CONFIG['RULES'][key]
    return CONFIG['RULES'][RULES_DEFAULT]


def parse_args():
    parser = argparse.ArgumentParser(
        description='Clean out old torrents from the transmission client via RPC')
    parser.add_argument('--host', '-H', default=None, type=str, help="Transmission RPC Host")
    parser.add_argument('--port', '-p', type=int, default=0, help="Transmission RPC Port")
    parser.add_argument('--user', '-u', default=None, help="Optional username", dest="user")
    parser.add_argument('--password', '-P', default=None, help="Optional password", dest='password')
    parser.add_argument('--generate_config', '-g', dest='generate', action='store_true',
                        help="Generate a config file that can be used to override defaults")
    parser.add_argument('--force', '-f', help="Overwrite existing files",
                        dest='force', action='store_true')
    return parser.parse_args()


def find_config():
    if not exists(CONFIG_FILE):
        return None
    return CONFIG_FILE


def mkdir_p(path):
    try:
        makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and isdir(path):
            pass
        else:
            raise


def generate_config(overwrite=False):
    if exists(CONFIG_FILE) and not overwrite:
        print("Config file exists already! Use -f to overwrite it.")
        return False
    if not exists(CONFIG_DIR):
        mkdir_p(CONFIG_DIR)
    with open(CONFIG_FILE, 'w') as cf:
        cf.write(dumps(CONFIG, sort_keys=True, indent=4, separators=(',', ': ')))
    return True


def load_config(path=None):
    global CONFIG
    if not path:
        path = find_config()
    if path and exists(path):
        CONFIG = load(open(path))
        print("Loaded config file: {}".format(path))
    return False


def make_client():
    args = parse_args()
    if args.generate:
        generate_config(args.force)
    load_config()
    return Client(
        args.host or CONFIG['CLIENT']['host'],
        port=args.port or CONFIG['CLIENT']['port'],
        user=args.user or CONFIG['CLIENT']['user'],
        password=args.password or CONFIG['CLIENT']['password']
    )


def remove_torrent(client, torrent, reason="None", dry_run=False):
    """ Remove a torrent from the client stopping it first if its in a started state.

    :param client: Transmission RPC Client
    :type client: transmissionrpc.Client
    :param torrent: Torrent instance to remove
    :type torrent: transmissionrpc.Torrent
    :param reason: Reason for removal
    :type reason: str
    :param dry_run: Do a dry run without actually running any commands
    :type dry_run: bool
    :return:
    """
    if torrent.status != "stopped":
        if not dry_run:
            client.stop_torrent(torrent.hashString)
    if not dry_run:
        client.remove_torrent(torrent.hashString, delete_data=False)
    print("Removed: {} {}\nReason: {}".format(torrent.name, torrent.hashString, reason))


def remove_unknown_torrents(client):
    """ Remove torrents that the remote tracker no longer tracking for whatever
    reason, usually removed by admins.

    :param client: Transmission RPC Client
    :type client: transmissionrpc.Client
    """
    for torrent in client.get_torrents():
        if torrent.error >= 2 and torrent.errorString.lower() in REMOTE_MESSAGES:
            remove_torrent(client, torrent)


def remove_local_errors(client):
    """ Removed torrents that have local filesystem errors, usually caused by moving data
    outside of transmission.

    :param client: Transmission RPC Client
    :type client: transmissionrpc.Client
    """
    for torrent in client.get_torrents():
        if torrent.error == 3:
            for errmsg in LOCAL_ERRORS:
                if errmsg in torrent.errorString.lower():
                    remove_torrent(client, torrent)
                    break


def clean_min_time_ratio(client):
    """ Remove torrents that are either have seeded enough time-wise or ratio-wise.
    The correct rule set is determined by checking the torrent announce url and
    matching it to a specific rule set defined above.

    :param client: Transmission RPC Client
    :type client: transmissionrpc.Client
    """
    for torrent in client.get_torrents():
        if torrent.error or torrent.status != "seeding":
            continue
        rule_set = find_rule_set(torrent.trackers)
        if torrent.ratio > rule_set['max_ratio']:
            remove_torrent(client, torrent, "max_ratio threshold passed", dry_run=False)
        if torrent.secondsSeeding > rule_set['min_time']:
            remove_torrent(client, torrent, "min_time threshold passed", dry_run=False)