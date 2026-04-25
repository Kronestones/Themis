# Themis — Tor Hidden Service Setup
# Run these commands in Termux after installing tor

# ── 1. Install tor in Termux ─────────────────────────────────────────────────
pkg install tor

# ── 2. Create torrc ──────────────────────────────────────────────────────────
mkdir -p ~/.tor/themis_hidden_service

cat > ~/.tor/torrc << 'TORRC'
SocksPort 9050
HiddenServiceDir /data/data/com.termux/files/home/.tor/themis_hidden_service
HiddenServicePort 80 127.0.0.1:5000
TORRC

# ── 3. Start tor ─────────────────────────────────────────────────────────────
tor -f ~/.tor/torrc &

# ── 4. Get your .onion address (wait ~30 seconds after starting) ─────────────
cat ~/.tor/themis_hidden_service/hostname
# Output: something like abc123xyz.onion

# ── 5. Keep tor running alongside Flask ──────────────────────────────────────
# In one Termux session:
tor -f ~/.tor/torrc

# In another (or use tmux):
cd ~/themis && python web.py

# ── 6. Add onion address to Themis footer ───────────────────────────────────
# In map.html, add to footer:
# <a href="http://YOUR_ADDRESS.onion">Also available on Tor</a>

# ── NOTES ────────────────────────────────────────────────────────────────────
# - The .onion address is stable — same address every time as long as
#   ~/.tor/themis_hidden_service/private_key exists. Back this up.
# - Render deployment won't have Tor — this is for the local Termux instance
#   OR a VPS. For permanent onion hosting, consider running on a cheap VPS
#   (e.g. $6/mo Hetzner) with the same torrc config.
# - termux-wake-lock keeps Termux alive while tor runs
# - To make permanent: add 'tor -f ~/.tor/torrc &' to ~/.bashrc

termux-wake-lock && tor -f ~/.tor/torrc &
