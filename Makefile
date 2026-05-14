PYTHON = python3
SRC = src
DATA = data
DIST = dist

.PHONY: all clean

all: $(DIST)/NIBBLE.LIBRARY.po

# Generate menu BASIC files + data files, then assemble the disk image
$(DIST)/NIBBLE.LIBRARY.po: $(DATA)/topic-assignments.json \
                            $(DATA)/dependency-map.json \
                            $(DATA)/docs-linkage.json \
                            $(SRC)/generate_menus.py \
                            $(SRC)/build_image.py
	mkdir -p $(DIST)
	$(PYTHON) $(SRC)/generate_menus.py
	$(PYTHON) $(SRC)/build_image.py

clean:
	rm -rf $(DIST)/
