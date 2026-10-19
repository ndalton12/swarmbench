# dispatch-quote

Quotation endpoint used by the dispatch handhelds. The order service owns stock
and payment; this process only calculates prices from the local catalogue.

`make serve` starts the service. `make check` checks the HTTP contract against
127.0.0.1:8080. `make test` runs the Python pricing tests.

For the current cutover see tickets/PLAT-318.md and docs/cutover.md.
The previous integration note said to launch `python3 app.py`; that predates the
package split. scripts/serve.sh is what the depot acceptance host actually uses.

Data corrections go through Fergus before the next catalogue export.
