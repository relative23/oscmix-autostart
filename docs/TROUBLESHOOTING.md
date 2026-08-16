# Troubleshooting

Work through the layers in order -- each one has a quick check.

## 1. Is the device on the bus?

```sh
grep -l 2a39 /sys/bus/usb/devices/*/idVendor   # any hit = connected
cat /proc/asound/cards                          # ALSA card registered?
```

No hit: cable/power/port problem, or USB autosuspend put the device to
sleep. The shipped udev rule sets `power/control=on` for the device; verify
with:

```sh
cat /sys/bus/usb/devices/<dev>/power/control    # should print "on"
```

On systems where the Fireface is connected through an ASMedia ASM4242
controller (`1b21:2426`), the same rule also disables runtime power
management for that controller. This avoids a failed xHCI runtime suspend
leaving its ports unable to enumerate the interface. Verify with the PCI
address reported by `lspci -Dnn`:

```sh
cat /sys/bus/pci/devices/0000:<bus>:00.0/power/control  # should print "on"
```

If `power/runtime_status` already says `error`, changing the policy cannot
repair the controller retroactively. Move the Fireface to a non-USB4 port or
cold-boot once; the rule prevents the same runtime suspend on later boots.

## 2. Is the MIDI control port there?

```sh
cat /proc/asound/seq/clients | grep -A3 Fireface
```

Expected: a client with two ports. Port 0 is regular MIDI, **port 1 is the
SysEx control port** oscmix needs. If the file does not exist, `snd-seq`
is not loaded (`sudo modprobe snd_seq`; oscmix-session normally triggers
this automatically by opening `/dev/snd/seq`).

## 3. Is the backend running?

```sh
systemctl --user status oscmix.service
journalctl --user -u oscmix.service -e --no-pager
oscmix-session --dry-run        # config parse + device discovery only
```

Common findings in the journal:

- `configuration error: ...` -- routing.conf problem; the message names
  the section and option. The service deliberately does **not** restart
  until you fix it and run `systemctl --user restart oscmix.service`.
- `USB device ... connected but no ALSA sequencer client` -- kernel/driver
  problem, see step 2.
- `device 2a39:3fd9 not connected; nothing to do` -- normal when the unit
  is off; the udev rule starts the service again on plug-in.
- `routing verified against device state` -- the read-back confirmed the
  hardware mixer matches routing.conf; this is the "everything works"
  line.
- `routing verification skipped: UDP 8222 in use` -- harmless; the mixer
  GUI was listening on the state port, so the read-back was not possible.
- `unconfirmed after retry: ...` -- the device never reported the listed
  registers back. Check them in the mixer GUI; if the audio is fine, the
  upstream dump format may simply have changed -- please open an issue.

- `no link change reported within ...` -- normal: the output pairs were
  already stereo-linked, so the device had no change to report.
- `mix matrix re-applied against the synchronized link state` -- the
  routing was re-established after the device's register sync. This is
  what guarantees the right-hand channel of every pair; see below.

The mix matrix is written twice on purpose. oscmix only learns that an
output pair is stereo-linked when the device reports `/output/<n>/stereo`
back, and it does not sync its register cache on its own -- it learns the
device's values only from a `/refresh` dump. A mix written before that
dump is evaluated against oscmix's startup link state and only reaches
the odd channel of each pair, so every even output (2, 4, 6, 8) stays
silent.

So the first write gets audio going immediately, and the background
verification pass -- whose dump is what syncs oscmix -- re-applies the
matrix the moment that dump reports the links. Unlike the `/output/*`
registers the matrix cannot be verified: a `/mix` write draws no reply
and the dump omits the playback matrix, so it is re-established rather
than checked. Both jobs deliberately share one `/refresh`; two
overlapping dumps starve each other and confirm fewer registers.

Only the blind fallback has a knob, for the case where the mixer GUI
holds UDP 8222 and the dump cannot be observed at all
(`systemctl --user edit oscmix.service`):

```ini
[Service]
Environment=OSCMIX_LINK_SYNC_DELAY=30
```

## 4. Does the backend accept OSC?

```sh
ss -ulnp | grep 7222            # oscmix should be listening
```

## 5. Sound on the wrong outputs / no sound

PipeWire maps the 8 analog outputs as 7.1 surround; stereo audio goes to
channels FL/FR = outputs 1/2. If your speakers are on other outputs, route
them in `~/.config/oscmix/routing.conf`:

```ini
[route:monitors]
playback = 1/2
output = 5/6      # wherever your speakers are connected
```

then `systemctl --user restart oscmix.service`. The routing happens in the
device's hardware mixer, so it works the same under PipeWire, PulseAudio
and JACK.

## 6. Service does not start on hotplug

```sh
udevadm test --action=add $(udevadm info -q path -n /dev/bus/usb/00X/00Y) 2>&1 \
  | grep -i systemd_user_wants
```

If nothing matches, re-install the udev rule:

```sh
sudo install -m 644 udev/90-rme-fireface.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Note that hotplug start requires a running systemd *user* session (i.e.
you are logged in). Before login the service cannot run; it is also pulled
in via `default.target` at login, which covers the boot-with-device-on
case.

## 7. GUI crashes immediately

`oscmix-gtk` aborts if its GSettings schema is missing. `install.sh`
installs and compiles it under `~/.local/share/glib-2.0/schemas/`; verify:

```sh
ls ~/.local/share/glib-2.0/schemas/gschemas.compiled
```

If you built oscmix manually, run:

```sh
install -D -m644 build/oscmix/gtk/oscmix.gschema.xml \
  ~/.local/share/glib-2.0/schemas/oscmix.gschema.xml
glib-compile-schemas ~/.local/share/glib-2.0/schemas
```
