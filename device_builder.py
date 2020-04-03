#!/usr/bin/env python

import optparse
import sys
import packet
import os
import json
from time import time
from time import sleep
from http import client as httplib
from datetime import datetime as dt


def spinning_cursor():
    while True:
        for cursor in '|/-\\':
            yield cursor


def pretty_sleep(seconds):
    spinner = spinning_cursor()
    for _ in range(int(round(seconds * 10))):
        sys.stdout.write(next(spinner))
        sys.stdout.flush()
        sleep(0.1)
        sys.stdout.write('\b')


def parse_args():
    parser = optparse.OptionParser(
        usage="\n\t%prog -f <facility_list> -p <device_plan> -o <operating_system>"
              "\n\t\t\t  [-q <number>] [-t <time_seconds> [-a <api_key>]"
              "\n\t\t\t  [-i <project_id>] [-c <consumer_token>")
    parser.add_option('-f', '--facility', dest="facility", action="store",
                      help="List of facilities to deploy servers. Example: ewr1,sjc1")
    parser.add_option('-p', '--plan', dest="plan", action="store",
                      help="Device plan to deploy. Example: c3.small.x86")
    parser.add_option('-o', '--os', dest="os", action="store",
                      help="Operating System to deploy on the Device. Example: ubuntu_18_04")
    parser.add_option('-q', '--quantity', dest="quantity", action="store", default=1,
                      help="Number of devices to deploy per facility. Example: 100")
    parser.add_option('-t', '--timeout', dest="timeout", action="store", default=15,
                      help="Amount of time to wait for devices to become active. Example: 25")
    parser.add_option('-a', '--api_key', dest="api_key", action="store", default=None,
                      help="Packet API Key. Example: vuRQYrg2nLgSvoYuB8UYSh4mAHFACTHB")
    parser.add_option('-i', '--project_id', dest="project_id", action="store", default=None,
                      help="Packet Project ID. Example: ecd8e248-e2fb-4e5b-b90e-090a055437dd")
    parser.add_option('-c', '--consumer_token', dest="consumer_token", action="store", default=None,
                      help="Packet Consumer Token. "
                           "Example: 8wtcigw6j1px9obscksorhpn48gz3evbgoqizcnsm7t7wdsjfmy00a3ng9p8t1d4")
    # TODO: There migth be a desire to not cleanup... Maybe I should add a --skip-cleanup flag.

    options, _ = parser.parse_args()
    if not (options.facility and options.plan and options.os):
        print("ERROR: Missing arguments")
        parser.print_usage()
        sys.exit(1)

    if not options.api_key:
        options.api_key = os.getenv('PACKET_AUTH_TOKEN')

    if not options.api_key:
        print("ERROR: API Key is required ether pass it in via the command line or export 'PACKET_AUTH_TOKEN'")
        sys.exit(1)

    if not options.consumer_token:
        options.consumer_token = os.getenv('PACKET_CONSUMER_TOKEN')

    if not options.consumer_token:
        print("ERROR: Consumer Token is required ether pass it in via the command line or export "
              "'PACKET_CONSUMER_TOKEN'")
        sys.exit(1)

    if not options.project_id:
        options.project_id = os.getenv('PACKET_PROJECT_ID')

    if not options.project_id:
        print("ERROR: Project ID is required ether pass it in via the command line or export 'PACKET_PROJECT_ID'")
        sys.exit(1)
    options.all = False
    try:
        options.quantity = int(options.quantity)
    except:
        if options.quantity.lower() == 'all':
            options.all = True
        else:
            print("ERROR: Quantity must be a valid integer. Example: 5")
            sys.exit(1)
    try:
        options.timeout = int(options.timeout)
    except:
        print("ERROR: Timeout must be a valid integer. Example: 25")
        sys.exit(1)
    options.facilities = options.facility.split(",")
    return options


def authenticate(args):
    headers = {
        "Accept": "application/json",
        "X-Auth-Token": args.api_key,
        "X-Consumer-Token": args.consumer_token,
        "X-Packet-Staff": "true"
    }
    try:
        _, response = do_request("GET", "api.packet.net", "/staff/labels", headers, "")
        if response.status != 200 and response.status != 201:
            print("ERROR: Could not validate Auth Token.")
            sys.exit(1)
        else:
            manager = packet.Manager(auth_token=args.api_key)
    except:
        print("ERROR: Could not validate Auth Token.")
        sys.exit(1)

    return manager


def do_request(action, host, relative_url, headers, body):
    conn = httplib.HTTPSConnection(host)
    if body == "":
        the_json = body
    else:
        the_json = json.JSONEncoder().encode(body)
    conn.request(action, relative_url, the_json, headers)
    response = conn.getresponse()
    return conn, response


def insert_record(body):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Auth-Token": "222b7564-a0f8-4d90-84a9-5a9f4684b3ea"
    }
    _, response = do_request("POST", "packet.codyhill.co", "/insert", headers, body)
    if response.status != 200 and response.status != 201:
        print("Error inserting record!")
        print("{}: {}".format(response.status, response.reason))
        sys.exit(1)


def create_devices(args, manager):
    devices = []

    for facility in args.facilities:
        if args.all is True:
            quantity = args.max_quantity[facility]
        else:
            quantity = args.quantity
        for i in range(quantity):
            mod_plan = args.plan.replace("_", "-").replace(".", "-")
            mod_os = args.os.replace("_", "-").replace(".", "-")
            hostname = "{}-{}-{}-{}".format(facility, mod_plan, mod_os, i)
            print("Creating {}".format(hostname))
            try:
                devices.append(manager.create_device(args.project_id, hostname, args.plan, facility, args.os))
            except packet.baseapi.Error as e:
                print(e)
                print("\tAPI error creating device: {}. Skipping...".format(hostname))
            except:
                print("Unknown error creating device: {}. Skipping...".format(hostname))
            pretty_sleep(0.5)

    return devices


def poll_devices(args, manager, devices):
    timeout = time() + (args.timeout * 60)
    while len(devices) != 0:
        print("Checking if devices are active. {} devices left...".format(len(devices)))
        for device in devices:
            print("Checking if {} is active".format(device['hostname']))
            try:
                poll_device = manager.get_device(device['id'])
            except:
                print("Failed to find device with id: {}. Skipping Device. "
                      "This may require manual cleanup".format(device['id']))
                devices.remove(device)
                # TODO: Insert something into the Database with the info we've gathered...
                next

            if poll_device['state'] == 'active':
                print("{} is active!".format(poll_device['hostname']))
                create = dt.strptime(poll_device['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                finish = dt.strptime(poll_device['updated_at'], "%Y-%m-%dT%H:%M:%SZ")
                duration = (finish - create).total_seconds()
                #insert_record({
                #    'uuid': poll_device['id'],
                #    'state': poll_device['state'],
                #    'hostname': poll_device['hostname'],
                #    'facility': poll_device['facility']['code'],
                #    'plan': poll_device['plan']['name'],
                #    'operating_system': poll_device['operating_system']['slug'],
                #    'created_at': create.strftime('%Y-%m-%d %H:%M:%S'),
                #    'updated_at': finish.strftime('%Y-%m-%d %H:%M:%S'),
                #    'creation_duration': duration
                #})
                devices.remove(device)
                print("Deleting {}!".format(poll_device['hostname']))
                poll_device.delete()
            elif poll_device['state'] in ('deprovisioning', 'failed', 'inactive'):
                print("Devices is in state: {}. Skipping Device. "
                      "This may require manual cleanup".format(device['id']))
                devices.remove(device)
                # TODO: Insert something into the Database with the info we've gathered...
            pretty_sleep(0.5)
        if time() > timeout:
            print("The following devices have timedout after {} seconds. "
                  "You may need to investigate: {}".format(args.timeout, devices))
            timeout_devices(manager, devices)
            break
        else:
            seconds = (timeout - time())
            minutes, seconds = divmod(seconds, 60)
            print("{}:{} until timeout...".format(round(minutes), round(seconds)))
        print("Will check again in 10 seconds...")
        pretty_sleep(10)


def timeout_devices(manager, devices):
    for device in devices:
        try:
            poll_device = manager.get_device(device['id'])
        except:
            print("Failed to find device with id: {}. Skipping Device. "
                  "This may require manual cleanup".format(device['id']))
            devices.remove(device)
            # TODO: Insert something into the Database with the info we've gathered...
            next
        create = dt.strptime(poll_device['created_at'], "%Y-%m-%dT%H:%M:%SZ")
        finish = time()
        duration = (finish - create).total_seconds()
        #insert_record({
        #    'uuid': poll_device['id'],
        #    'state': "timedout",
        #    'hostname': poll_device['hostname'],
        #    'facility': poll_device['facility']['code'],
        #    'plan': poll_device['plan']['name'],
        #    'operating_system': poll_device['operating_system']['slug'],
        #    'created_at': create.strftime('%Y-%m-%d %H:%M:%S'),
        #    'updated_at': finish.strftime('%Y-%m-%d %H:%M:%S'),
        #    'creation_duration': duration
        #})


def validate_args(args, manager):
    os_list = manager.list_operating_systems()
    plan_list = manager.list_plans()
    facility_list = manager.list_facilities()

    os_valid = False
    for op_system in os_list:
        if op_system.slug == args.os:
            os_valid = True
            break
    if os_valid is False:
        print("ERROR: {} is not a valid operating system!".format(args.os))
        sys.exit(1)

    plan_valid = False
    for plan in plan_list:
        if plan.slug == args.plan or plan.name == args.plan:
            args.plan = plan.slug
            plan_valid = True
            break
    if plan_valid is False:
        print("ERROR: {} is not a valid plan!".format(args.plan))
        sys.exit(1)

    for site in args.facilities:
        facility_valid = False
        for facility in facility_list:
            if facility.code == site:
                facility_valid = True
                break
        if facility_valid is False:
            print("ERROR: {} is not a valid facility!".format(site))
            sys.exit(1)

    if args.all is True:
        args.quantity = {}
        args.max_quantity = get_max(args)


def get_max(args):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Auth-Token": args.api_key,
        "X-Consumer-Token": args.consumer_token,
        "X-Packet-Staff": "true"
    }
    _, response = do_request("GET", "api.packet.net", "/capacity", headers, "")
    if response.status != 200 and response.status != 201:
        print("ERROR: Could not get capcity...")
        sys.exit(1)

    response_body = json.loads(response.read().decode('utf-8'))
    device_max = {}
    for facility in args.facilities:
        try:
            device_max[facility] = response_body['capacity'][facility][args.plan]['available_servers']
        except:
            print("Plan: {} doesn't seem to be valid for Facility: {}. Skipping Facility.".format(args.plan, facility))
            device_max[facility] = 0

    return device_max


def main():
    args = parse_args()
    manager = authenticate(args)
    print("Authenticated successfully.")
    validate_args(args, manager)
    print("Command line arguments are valid.")
    devices = create_devices(args, manager)
    print("All devices created!")
    print("Sleeping 30 seconds before polling...")
    pretty_sleep(30)
    print("Polling Devices...")
    poll_devices(args, manager, devices)
    print("All devices have completed.")
    print("Done!")


if __name__ == "__main__":
    main()
