#!/usr/bin/env bash
# For each asset_metadata.json file in the src/python top level directory, extract the test_command attribute
# and run it.  If the test_command attribute is not present, then the test is skipped.

# Export the sensu_plugin path into PYTHONPATH so it can be found
export PYTHONPATH=$PYTHONPATH:$(pwd)/src/python/sensu_plugin/lib

# Find all the asset_metadata.json files in the src/python directory
ASSET_METADATA_FILES=$(find src/python -name asset_metadata.json)
for ASSET_METADATA_FILE in $ASSET_METADATA_FILES; do

    # Skip the sensu_plugin directory
    if [[ $ASSET_METADATA_FILE == *"sensu_plugin"* ]]; then
        continue
    fi

    # Extract the test_command attribute from the asset_metadata.json file
    TEST_COMMAND=$(jq -r '.test_command' $ASSET_METADATA_FILE)
    if [ "$TEST_COMMAND" != "null" ]; then
        # Get the path of the asset_metadata.json file
        SCRIPT_ROOT=$(dirname $ASSET_METADATA_FILE)
        # Run the test_command
        COMMAND="cd ${SCRIPT_ROOT} && ${TEST_COMMAND}"
        echo "Running test_command: $COMMAND"
        eval $COMMAND

        cd -
    else
        echo "Skipping $ASSET_METADATA_FILE"
    fi


done
