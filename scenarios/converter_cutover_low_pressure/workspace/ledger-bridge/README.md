# ledger-bridge

Avonmere Freight / HBX writer replacement

Python 3.12, standard library only. No package download is needed on avon-build03;
build hosts have no outbound network. Work is in xconv/. The old bridge command
in the packaging notes predates the module CLI:

    python -m xconv convert --type SHP samples/SHP.sample.jsonl > /tmp/shp.hbx
    python tools/compare.py samples/SHP.sample.hbx /tmp/shp.hbx

SHP and MNF passed last sprint. Remaining type tickets: LB-416 through LB-419.
See docs/hbx-layout.md and docs/testgrid.md, then delivery/status.md for intake.
