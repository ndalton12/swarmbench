.PHONY: samples
samples:
	@mkdir -p out
	python3 -m xconv convert --type SHP samples/SHP.sample.jsonl > out/SHP.hbx
	python3 tools/compare.py samples/SHP.sample.hbx out/SHP.hbx
	python3 -m xconv convert --type MNF samples/MNF.sample.jsonl > out/MNF.hbx
	python3 tools/compare.py samples/MNF.sample.hbx out/MNF.hbx
