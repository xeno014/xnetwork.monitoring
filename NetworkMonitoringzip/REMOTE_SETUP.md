# Monitoring and speed-testing a device in another location

This guide connects your monitoring PC to a device somewhere else using
**Tailscale** (free for personal use), then installs the **XenoTech Speed Agent**
on that device so you can run real download/upload speed tests on it.

Terms: **Monitor PC** = the PC running XenoTech IP Monitor.
**Remote device** = the Windows PC/laptop at the other location.

---

## Part 1: Tailscale

Tailscale creates a private network between your devices over the internet.
Every device gets a stable private address like `100.101.102.103`. It works
behind any router, including ISPs that don't give you a public IP.

### On the Monitor PC
1. Go to **tailscale.com/download** and install Tailscale for Windows.
2. Click **Log in** and sign in (Google, Microsoft, GitHub, or Apple account).
   Use the **same account** on every device.
3. The tray icon turns active. Right-click it to see your address (`100.x.x.x`).

### On the remote device
1. Install Tailscale from the same page.
2. Sign in with the **same account** as the Monitor PC.
3. In the Tailscale tray menu, find this device's address (`100.x.x.x`). Write it down.
4. Optional but recommended: in the Tailscale admin page
   (**login.tailscale.com/admin/machines**), open the device's menu and choose
   **Disable key expiry** so it never needs to log in again.
5. Set Tailscale to start with Windows (Tailscale Preferences > **Run unattended**
   / **Start on login**).

### Allow ping on the remote device
The monitor checks devices with ping, and Windows blocks ping by default. On the
**remote device**, open **Command Prompt as Administrator** and run:

```
netsh advfirewall firewall add rule name="Allow ICMPv4 Ping" protocol=icmpv4:8,any dir=in action=allow
```

### Test it
On the Monitor PC, open Command Prompt and run `ping 100.x.x.x` (the remote
device's Tailscale address). You should see replies.

### Add it to XenoTech IP Monitor
1. Open the app > **Devices** > **Add Device**.
2. Name it (for example `Branch Office PC`) and enter the `100.x.x.x` address.
3. It now shows ONLINE/OFFLINE like any other device, and you'll get Discord
   alerts and `/status` results for it.

---

## Part 2: Speed Agent (for speed tests on the remote device)

Ping can only say "up or down". To measure the remote device's **own internet
speed**, a tiny program must run on that device.

### Build the agent (on the Monitor PC, once)
Double-click **build_agent.bat**. It creates `dist\XenoTechSpeedAgent.exe`.

### Choose a token
Make up a secret of at least 8 characters, for example `Xeno-Speed-9382`.
The same token goes on the remote device and in the app.

### Run it on the remote device
1. Copy `XenoTechSpeedAgent.exe` to the remote device (for example `C:\XenoAgent\`).
2. Open Command Prompt there and run (use the device's own Tailscale address):

   ```
   XenoTechSpeedAgent.exe --token Xeno-Speed-9382 --bind 100.101.102.103
   ```

   Binding to the Tailscale address means only your private Tailscale network
   can reach the agent. Using `--bind 0.0.0.0` also listens on the local network.
3. If Windows asks about the firewall, tick **Private networks** and click
   **Allow access**. If it never asks and tests fail, allow the exe through
   Windows Defender Firewall (inbound, TCP port 8765).
4. Leave the window open. You should see
   `XenoTech Speed Agent listening on 100.101.102.103:8765`.

### Start the agent automatically with Windows
On the remote device, in Command Prompt as Administrator:

```
schtasks /Create /TN "XenoTech Speed Agent" /SC ONSTART /RL HIGHEST /RU SYSTEM /TR "C:\XenoAgent\XenoTechSpeedAgent.exe --token Xeno-Speed-9382 --bind 100.101.102.103"
```

Use your own path, token, and address. To remove it later:
`schtasks /Delete /TN "XenoTech Speed Agent" /F`

### Tell the app the token
In XenoTech IP Monitor > **Settings**, set **Speed agent token** to the same
secret (and **Speed agent port** if you changed `--port`), then click **Save Settings**.

---

## Using speed tests

**In the app: Speed Test tab**
- **This PC (internet)**: the Monitor PC's own internet speed. Needs no agent.
- **A device + "Its internet"**: that device's own internet speed (runs on the device).
- **A device + "Link to this PC"**: raw speed of the path between the two locations
  (through Tailscale). Useful for judging the connection between sites.
- **Test All Devices**: tests this PC, then every monitored device that is not
  OFFLINE and has the agent running. Devices without the agent show an error and
  are skipped.

**In Discord**
- `/speedtest`: this PC's internet
- `/speedtest device:Branch Office PC`: that device's internet
- `/speedtest device:Branch Office PC link:True`: the link between the sites

Every result is saved to `logs\speedtests.csv` (opens in Excel).

## Notes
- Speeds are in **Mbps** (megabits per second). Divide by 8 for MB/s.
- A test uses real data: roughly 100-400 MB total per run on a fast connection.
  Be careful on metered or capped connections.
- Results vary with other traffic and with the test server; run it a few times.
- Only one test runs at a time on a PC, so they never fight each other.
- Keep the token private. Anyone with it who can reach the agent can start tests.
