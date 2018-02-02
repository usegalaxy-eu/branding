LOGOS := $(sort $(wildcard *.svg))
SVGCONVERT := node_modules/.bin/svgexport
INV_LOGOS := $(LOGOS:svg=inv.svg)
PNG_LOGOS := $(LOGOS:svg=png) $(INV_LOGOS:svg=png)

all: $(PNG_LOGOS:.png=) ## Default target to make png files

node_modules: package.json yarn.lock ## Install svgexport
	yarn install

%.inv.svg: %.svg ## Convert normal SVGs to inverted versions for dark backgrounds
	sed 's|#003399|#ffffff|g' < $< > $@

%: %.svg  node_modules ## Main task to build all SVGs
	mkdir -p $@
	$(SVGCONVERT) $< $@/$@.png png 100% 5x
	gm convert -background none -resize 128  $@/$@.png $@/$@.128.png
	gm convert -background none -resize 256  $@/$@.png $@/$@.256.png
	gm convert -background none -resize 512  $@/$@.png $@/$@.512.png
	gm convert -background none -resize 1024  $@/$@.png $@/$@.1024.png
	optipng $@/$@.128.png
	optipng $@/$@.256.png
	optipng $@/$@.512.png
	optipng $@/$@.1024.png
	optipng $@/$@.png

clean:
	@rm -rf $(LOGOS:.svg=) $(INV_LOGOS:.svg=)

help:
	@egrep '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: clean help
