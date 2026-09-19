"""Idempotent schema/index migration for an explicitly authorized NEW database."""
import argparse,json
from asuna.config import load
from asuna.state import Store

parser=argparse.ArgumentParser();parser.add_argument('--config',default='config/local.json');parser.add_argument('--database')
args=parser.parse_args();store=Store(load(args.config),args.database)
try:print(json.dumps(store.migrate()))
finally:store.client.close()
