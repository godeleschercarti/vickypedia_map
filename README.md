This Python file creates a PNG world map of the Victoria 3 game map and code for a clickable ImageMap Wikimedia file. To use:

- Download and create an input and output folder in the directory
- Place a copy of all requisite input files in the input folder (see below)
- Edit the Python file if you want to make graphical changes, or to update game details

Requisite input files:

- COUNTRY_COLOURS = "input/country_definitions" # Found in common
- COUNTRY_PROVINCES = "input/00_states.txt" # Found in common/history/states
- SUBJECT_RELATIONSHIPS = "input/00_subject_relationships.txt" # Found in common/history/diplomacy
- PROVINCE_PNG = "input/provinces.png" #Found in game/map_data
- SEA_DETAILS = "input/default.map" #found in game/map_data
- LOCALISATION_YAML = "input/countries_l_english.yml" #Found in localization/english (can be any language, but untested)
