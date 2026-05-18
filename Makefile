PYTHON = python3
SRC = src
DATA = data
DIST = dist
PO = Nibble 1 and 2 liner collection.po

.PHONY: all clean

all: $(DIST)/$(PO)

# Generate menu BASIC files + data files, then assemble the disk image
$(DIST)/$(PO): $(DATA)/topic-assignments.json \
                            $(DATA)/dependency-map.json \
                            $(DATA)/docs-linkage.json \
                            $(SRC)/generate_menus.py \
                            $(SRC)/build_image.py
	mkdir -p $(DIST)
	$(PYTHON) $(SRC)/generate_menus.py
	$(PYTHON) $(SRC)/build_image.py

clean:
	rm -rf $(DIST)/
