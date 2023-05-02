# Sensu Assets

This repo contains a connection of basic Sensu assets to that can be used as a base to run a simple Sensu server.

Assets are organised by scrip language, so that assets can be build consistently, and in their own way where necessary

See the [sensu-asset-builder](https://github.com/adammcdonagh/sensu-asset-builder) repo for a way to automate the packaging of these scripts into actual Sensu assets that can be directly imported into Sensu.

## Metadata

The below assumes the use of the sensu-asset-builder code to actually build the assets.
 
Each asset needs to have it's own metadata. This is so that when building, and dependencies can be downloaded, as well as defining different operating systems (where packages may need compiling).

Below is an example `asset_metadata.json` file for an example asset:

```json
{
  "asset_name": "core/my_core_sensu_check", // suffix must match directory name
  "description": "An example sensu check asset",
  "version": "1.0",
  "type": "python",
  "python_version": "3.9.10",
  "requirements": ["boto3"], // This should not include any modules that there's already a runtime package for
  "systems": [
    {
      "os": "linux",
      "arch": "amd64",
      "platform_family": "rhel",
      "platform_version": 7,
      "sensu_filters": [
        "entity.system.os == 'linux'",
        "( entity.system.platform_family == 'rhel' || entity.system.platform_family == 'centos')",
        "parseInt(entity.system.platform_version.split('.')[0]) == 7"
      ]
    },
    {
      "os": "linux",
      "platform_family": "alpine",
      "sensu_filters": [
        "entity.system.os == 'linux'",
        "entity.system.platform_family == 'alpine'"
      ]
    }
  ]
}
```

The `platform_family` and `platform_version` attributes define how the operating system used to build the assets, and determine which docker image will be used. 

The `sensu_filters` attribute uses [Sensu query expressions](https://docs.sensu.io/sensu-go/latest/observability-pipeline/observe-filter/sensu-query-expressions/) to specify which Sensu agents each asset package will be deployed to, and hence which ones will be built. This is only important when there are compiled files within the package, and is unnecessary if the asset contains just a simple script.