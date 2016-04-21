import base64
import json
import re
import sys

import click
from click_default_group import DefaultGroup
import subprocess
from gi.repository import GLib, GObject
from pydbus import SystemBus


WPAS_BUS_NAME = 'fi.w1.wpa_supplicant1'
SSID_UNQUOTE = re.compile('"([^"]+)"')
NONSPACE = re.compile(r'\S')


def signal_strength(signal_dBm):
    # TODO ceil/floor should be configurable or
    #      auto-adjusted during runtime
    ceil = -20
    floor = -100
    delta = -floor
    signal_dBm += delta
    ceil += delta
    return 100 * signal_dBm / ceil


class InvalidInterfaceError(click.UsageError):
    """Raised no valid wireless interface was provided."""

    def __init__(self, name=None):
        if name:
            message = 'Invalid interface "{0}"'.format(name)
        else:
            message = ("Can't find a wireless interface. "
                       "Specify with --ifname.")
        super(InvalidInterfaceError, self).__init__(message)


@click.group(cls=DefaultGroup, default_if_no_args=True)
@click.option('--ifname', default=None, required=False,
              help='The wireless interface name')
@click.pass_context
def cli(ctx, ifname):
    if not ifname:
        try:
            # try to determine the interface name with "ip link"
            out = subprocess.check_output(
                "ip -o link | awk '{print $2}'", shell=True)
            match = re.search(r'(wl[^:]+):', out)
            if not match:
                raise InvalidInterfaceError()
            ifname = match.groups(1)[0]
        except:
            raise InvalidInterfaceError()
    # Get a reference to the wpa_supplicant main object
    bus = SystemBus()
    api = bus.get(WPAS_BUS_NAME)
    # Search in the interfaces controlled by wpa_supplicant for
    # an interface named `ifname`
    interface = None
    for path in api.Interfaces:
        iface = bus.get(WPAS_BUS_NAME, path)
        if iface.Ifname == ifname:
            interface = iface
            break
    if not interface:
        # If not found, try to register the interface in wpa_supplicant
        try:
            interface = bus.get(WPAS_BUS_NAME, api.CreateInterface({
                'Ifname': GLib.Variant('s', ifname)
            }))
        except:
            raise InvalidInterfaceError(ifname)
    # pass data to subcommand
    ctx.loop = GObject.MainLoop()
    ctx.bus = bus
    ctx.api = api
    ctx.interface = interface


@cli.command(default=True)
@click.option('-f', '--fields', type=click.Choice(
             ['ssid', 'wpa', 'rsn', 'wps', 'signal']),
             multiple=True,
             default=['ssid', 'wpa', 'rsn', 'wps', 'signal'],
             help='Fields to display')
@click.option('-s', '--sort', default=False,
              is_flag=True, required=False,
              help='Sort by signal strength')
@click.option('-h', '--human-readable', default=False,
              is_flag=True, required=False,
              help='Print signal strength as a percentage')
@click.pass_context
def scan(ctx, fields, sort, human_readable):
    loop = ctx.parent.loop
    bus = ctx.parent.bus
    interface = ctx.parent.interface
    def on_scan_done(success):
        if not success:
            raise click.ClickException(
                'failed to scan for access points with "{0}"'.format(
                    interface.Ifname))
        loop.quit()
    interface.onScanDone = on_scan_done
    interface.Scan({'Type': GLib.Variant('s', 'active')})
    loop.run()
    row = ''
    if 'ssid' in fields: row += '{ssid:<35}'
    if 'wpa' in fields: row += '{wpa:<5}'
    if 'rsn' in fields: row += '{rsn:<5}'
    if 'wps' in fields: row += '{wps:<5}'
    if 'signal' in fields: row += '{signal:>6}'
    aps = []
    for path in interface.BSSs:
        bss = bus.get(WPAS_BUS_NAME, path)
        signal = bss.Signal
        if human_readable:
            signal = '{0}%'.format(signal_strength(bss.Signal))
        aps.append(dict(ssid=''.join([chr(b) for b in bss.SSID]),
                        wpa='yes' if bss.WPA else 'no',
                        rsn='yes' if bss.RSN else 'no',
                        wps='yes' if bss.WPS and bss.WPS['Type'] else 'no',
                        signal=signal, strength=signal_strength(bss.Signal)))
    if sort:
        aps = sorted(aps, key=lambda ap: ap['strength'], reverse=True)
    click.echo(row.format(ssid='SSID', wpa='WPA', rsn='RSN',
                          wps='WPS', signal='Signal'))
    for ap in aps:
        click.echo(row.format(**ap))


@cli.command(name='list-networks')
@click.pass_context
def list_networks(ctx):
    bus = ctx.parent.bus
    interface = ctx.parent.interface
    for path in interface.Networks:
        network = bus.get(WPAS_BUS_NAME, path)
        click.echo(SSID_UNQUOTE.sub(r'\1', network.Properties['ssid']))


@cli.command(name='remove-network')
@click.argument('ssid')
@click.pass_context
def remove_network(ctx, ssid):
    bus = ctx.parent.bus
    interface = ctx.parent.interface
    removed = False
    for path in interface.Networks:
        network = bus.get(WPAS_BUS_NAME, path)
        if SSID_UNQUOTE.sub(r'\1', network.Properties['ssid']) == ssid:
            removed = True
            interface.RemoveNetwork(path)
    if not removed:
        raise click.ClickException(
            'Not connected to network "{0}"'.format(ssid))
        
            
@cli.command()
@click.argument('ssid')
@click.option('-s', '--save', required=False, type=click.File('ab'),
              help=('Save(append) connection data to a file for '
                    'later use with "load"'))
@click.pass_context
def connect(ctx, ssid, save):
    def on_properties_changed(properties):
        if 'State' not in properties:
            return
        state = properties['State']
        if state == 'authenticating':
            click.echo('Authenticating...')
        elif state == 'associating':
            click.echo('Associating...')
        elif state in ['completed', 'disconnected']:
            loop.quit()
    loop = ctx.parent.loop
    bus = ctx.parent.bus
    interface = ctx.parent.interface
    # Check if the network is already connected to
    for path in interface.Networks:
        network = bus.get(WPAS_BUS_NAME, path)
        if SSID_UNQUOTE.sub(r'\1', network.Properties['ssid']) == ssid:
            raise click.ClickException(
                'Already connected to network "{0}"'.format(ssid))
    # Scan for the ssid to obtain key_mgmt information
    # from the access point.
    interface.onScanDone = lambda s: loop.quit()
    interface.Scan({
        'Type': GLib.Variant('s', 'active'),
        'SSIDs': GLib.Variant('aay', [[ord(c) for c in ssid]])
    })
    loop.run()
    if not interface.BSSs:
        raise click.ClickException('scan for "{0}" failed'.format(ssid))
    bss = bus.get(WPAS_BUS_NAME, interface.BSSs[0])
    assert (''.join([chr(b) for b in bss.SSID])) == ssid
    network_data = {'ssid': GLib.Variant('s', ssid)}
    password = None
    if bss.WPA and 'wpa-none' not in bss.WPA['KeyMgmt']:
        # read password
        password = click.prompt('Enter password for "{0}"'.format(ssid),
                                hide_input=True)
        network_data['psk'] = GLib.Variant('s', password)
    path = interface.AddNetwork(network_data)
    network = bus.get(WPAS_BUS_NAME, path)
    network.Enabled = True
    interface.onPropertiesChanged = on_properties_changed
    loop.run()
    if interface.State == 'disconnected':
        interface.RemoveNetwork(path)
        raise click.ClickException(
            'Connection to "{0}" failed'.format(ssid))
    click.echo('Connection to "{0}" succeeded'.format(ssid))
    save.write('{0}\n'.format(json.dumps([ssid, password])))


@cli.command(help=('Load connection information from a file, '
                    'ignoring duplicates'))
@click.argument('input', type=click.File('rb'))
@click.pass_context
def load(ctx, input):
    loop = ctx.parent.loop
    bus = ctx.parent.bus
    interface = ctx.parent.interface
    # Build a cache of connected networks
    connected = {}
    for path in interface.Networks:
        network = bus.get(WPAS_BUS_NAME, path)
        connected[SSID_UNQUOTE.sub(r'\1', network.Properties['ssid'])] = True
    visited = {}
    for line in input:
        data = json.loads(line)
        if data[0] in visited:
            continue
        visited[data[0]] = True
        if data[0] in connected:
            click.echo('Ignoring "{0}"'.format(data[0]))
            continue
        click.echo('Adding "{0}"'.format(data[0]))
        network_data = {'ssid': GLib.Variant('s', data[0])}
        if data[1]:
            network_data['psk'] = GLib.Variant('s', data[1])
        path = interface.AddNetwork(network_data)
        network = bus.get(WPAS_BUS_NAME, path)
        network.Enabled = True
