Configuration
=============

The following files, by default located in ``/etc/arouteserver``, contain configuration options for the program and for the route server's configuration:

- ``arouteserver.yml``: program's options and paths to other files are configured here.
  See its default content on `GitHub <https://github.com/pierky/arouteserver/blob/master/config.d/arouteserver.yml>`_.

- ``general.yml``: this is the most important configuration file, where the route server's options and policies are configured.
  See its default content on `GitHub <https://github.com/pierky/arouteserver/blob/master/config.d/general.yml>`_.

- ``clients.yml``: the list of route server's clients and their options and policies.
  See its default content on `GitHub <https://github.com/pierky/arouteserver/blob/master/config.d/clients.yml>`_.

- ``bogons.yml``: the list of bogon prefixes automatically discarded by the route server.
  See its default content on `GitHub <https://github.com/pierky/arouteserver/blob/master/config.d/bogons.yml>`_.

Route server's configuration
----------------------------

Route server's general configuration and policies are outlined in the ``general.yml`` file. 

Configuration details and options can be found within the distributed `general <https://github.com/pierky/arouteserver/blob/master/config.d/general.yml>`_ and `clients <https://github.com/pierky/arouteserver/blob/master/config.d/clients.yml>`_ configuration files on GitHub.

Details about some particular topics are reported below.

.. contents::
   :local:

Client-level options inheritance
********************************

Clients, which are configured in the ``clients.yml`` file, inherit most of their options from those provided in the ``general.yml`` file, unless their own configuration sets more specific values.

Options that are inherited by clients and that can be overwritten by their configuration are highlighted in the ``general.yml`` template file that is distributed with the project.

Example:

**general.yml**

.. code:: yaml

   cfg:
     rs_as: 999
     router_id: "192.0.2.2"
     passive: True
     gtsm: True

**clients.yml**

.. code:: yaml

   clients:
     - asn: 11
       ip: "192.0.2.11"
     - asn: 22
       ip: "192.0.2.22"
       passive: False
     - asn: 33
       ip: "192.0.2.33"
       passive: False
       gtsm: False

In this scenario, the route server's configuration will look like this:

- a passive session with GTSM enabled toward AS11 client;
- an active session with GTSM enabled toward AS22 client;
- an active session with GTSM disabled toward AS33 client.

IRRDBs-based filtering
**********************

The ``filtering.irrdb`` section of the configuration files allows to use IRRDBs information to filter or to tag routes entering the route server. Information are acquired using the external program `bgpq3 <https://github.com/snar/bgpq3>`_: installations details on :doc:`INSTALLATION` page.

One or more AS-SETs can be used to gather information about authorized origin ASNs and prefixes that a client can announce to the route server. AS-SETs can be set in the ``clients.yml`` file on a two levels basis:

- within the ``asns`` section, one or more AS-SETs can be given for each ASN of the clients configured in the rest of the file;

- for each client, one or more AS-SETs can be configured in the ``cfg.filtering.irrdb`` section.

To gather information from the IRRDBs, at first the script uses the AS-SETs provided in the client-level configuration; if no AS-SETs are provided there, it looks to the ASN configuration. If no AS-SETs are found in both the client and the ASN configuration, only the ASN's autnum object will be used.

Example:

**clients.yml**

.. code:: yaml

   asns:
     AS22:
       as_sets:
         - "AS-AS22MAIN"
     AS33:
       as_sets:
         - "AS-AS33GLOBAL"
   clients:
     - asn: 11
       ip: "192.0.2.11"
       cfg:
         filtering:
           irrdb:
             as_sets:
               - "AS-AS11NETS"
     - asn: 22
       ip: "192.0.2.22"
     - asn: 33
       ip: "192.0.2.33"
       cfg:
         filtering:
           irrdb:
             as_sets:
               - "AS-AS33CUSTOMERS"
     - asn: 44
       ip: "192.0.2.44"

With this configuration, the following values will be used to run the bgpq3 program:

- **AS-AS11NETS** will be used for 192.0.2.11 (it's configured at client-level for that client);
- **AS-AS22MAIN** for the 192.0.2.22 client (it's inherited from the ``asns``-level configuration of AS22, client's AS);
- **AS-AS33CUSTOMERS** for the 192.0.2.33 client (the ``asns``-level configuration is ignored because a more specific one is given at client-level);
- **AS44** for the 192.0.2.44 client, because no AS-SETs are given at any level.

RPKI-based filtering
********************

RPKI-based validation of routes can be configured using the general ``filtering.rpki`` section. Depending on the ``reject_invalid`` configuration, routes can be rejected or tagged with BGP communities.

- To acquire RPKI data and load them into BIRD, a couple of external tools from the `rtrlib <http://rpki.realmv6.org/>`_ suite are used: `rtrlib <https://github.com/rtrlib>`_ and `bird-rtrlib-cli <https://github.com/rtrlib/bird-rtrlib-cli>`_. One or more trusted local validating caches should be used to get and validate RPKI data before pushing them to BIRD. An overview is provided on the `rtrlib GitHub wiki <https://github.com/rtrlib/rtrlib/wiki/Background>`_, where also an `usage guide <https://github.com/rtrlib/rtrlib/wiki/Usage-of-the-RTRlib>`_ can be found.

- RPKI validation is not supported by OpenBGPD.

BGP Communities
***************

BGP communities can be used for many features in the configurations built using ARouteServer: blackhole filtering, AS_PATH prepending, announcement control, various informative purposes (valid ASN, RPKI status, ...) and more. All these communities are referenced by *name* (or *tag*) in the configuration files and their real values are reported only once, in the ``communities`` section of the ``general.yml`` file.
For each community, values can be set for any of the three *formats*: standard (`RFC1997 <https://tools.ietf.org/html/rfc1997>`_), extended (`RFC4360 <https://tools.ietf.org/html/rfc4360>`_/`RFC5668 <https://tools.ietf.org/html/rfc5668>`_) and large (`draft-ietf-idr-large-community <https://tools.ietf.org/html/draft-ietf-idr-large-community>`_).

.. _site-specific-custom-config:

Site-specific custom configuration files
****************************************

Local configuration files can be used to load static site-specific options into the BGP speaker, bypassing the dynamic ARouteServer configuration building mechanisms. These files can be used to configure, for example, neighborship with peers which are not route server members or that require custom settings.

- In BIRD, *include* statements are used to add local files at the end of the main configuration file.
  Depending on the IP version that is in use to build the current configuration, an address family specific *include* statement is also added:

  .. code::

      # include statements for IPv4 configuration files
      include "*.local";
      include "*.local4";

  .. code::

      # include statements for IPv6 configuration files
      include "*.local";
      include "*.local6";

  
  Every file that is put into the same directory of the BIRD main configuration file and whose name matches the "\*.local" or "\*.local[4|6]" pattern is added to the end of the configuration. These files are not processed by ARouteServer but only by BIRD. Configuration options given in .local files must be IP version agnostic and must be supported by both the IPv4 and IPv6 processes; address family specific options must be set in .local4 or .local6 files.

  Example: file name "01-route_collector.local4" in "/etc/bird" directory:

  .. code::

      protocol bgp RouteCollector {
      	local as 999;
      	neighbor 192.0.2.99 as 65535;
      	rs client;
         	secondary;
      
      	import none;
      	export all;
      }

- For OpenBGPD, local files inclusion can be enabled by a command line argument, ``--use-local-files``: there are some fixed points in the configuration files generated by ARouteServer where local files can be included, and they are identified by the following labels:

  .. autoattribute:: pierky.arouteserver.builder.OpenBGPDConfigBuilder.LOCAL_FILES_IDS

  One or more of these labels must be used as the argument's value in order to enable the relative inclusion points.
  For each enabled label, an ``include "/etc/bgpd/LABEL.local"`` statement is added to the generated configuration in the point identified by the label itself. To modify the base directory, the ``--local-files-dir`` command line option can be used.

  Examples:

  .. code-block:: console

     $ arouteserver openbgpd --use-local-files header post-clients
     include "/etc/bgpd/header.local"
     
     AS 999
     router-id 192.0.2.2

     [...]

     group "clients" {
     
             neighbor 192.0.2.11 {
                     [...]
             }
     }
     
     include "/etc/bgpd/post-clients.local"
     
     [...]

  In the example above, the ``header`` and ``post-clients`` inclusion points are enabled and allow to insert two ``include`` statements into the generated configuration: one at the start of the file and one between clients declaration and filters.

  .. code-block:: console

     $ arouteserver openbgpd --use-local-files client footer --local-files-dir /etc/
     AS 999
     router-id 192.0.2.2
     
     [...]
     
     group "clients" {
     
             neighbor 192.0.2.11 {
                     include "/etc/client.local"
                     [...]
             }
     
             neighbor 192.0.2.22 {
                     include "/etc/client.local"
                     [...]
             }
     }
     
     [...]
     
     include "/etc/footer.local"

  The example above uses the ``client`` label, that is used to add an ``include`` statement into every neighbor configuration. Also, the base directory is set to ``/etc/``.

Caveats and limitations
***********************

Not all features offered by ARouteServer are supported by both BIRD and OpenBGPD.
The following list of limitations is based on the currently supported versions of BIRD (1.6.3) and OpenBGPD (OpenBSD 6.0).

- OpenBGPD

  - Currently, **path hiding** mitigation is not implemented for OpenBGPD configurations. Only single-RIB configurations are generated.

  - **RPKI** validation is not supported by OpenBGPD.

  - **ADD-PATH** is not supported by OpenBGPD.

  - For max-prefix filtering, only the ``shutdown`` and the ``restart`` actions are supported by OpenBGPD. Restart is configured with a 15 minutes timer.

  - `An issue <https://github.com/pierky/arouteserver/issues/3>`_ is currently preventing next-hop rewriting for **IPv6 blackhole filtering** policies.

  - **Large communities** are not supported by OpenBGPD: features that are configured to be offered via large communities only are ignored and not included into the generated OpenBGPD configuration.

  - OpenBGPD does not offer a way to delete **extended communities** using wildcard (``rt xxx:*``): peer-ASN-specific extended communities (such as ``prepend_once_to_peer``, ``do_not_announce_to_peer``) are not scrubbed from routes that leave OpenBGPD route servers and so they are propagated to the route server clients.

Depending on the features that are enabled in the ``general.yml`` and ``clients.yml`` files, compatibility issues may arise; in this case, ARouteServer logs one or more errors, which can be then acknowledged and ignored using the ``--ignore-issues`` command line option:

.. code-block:: console

   $ arouteserver openbgpd
   ARouteServer 2017-03-23 21:39:45,955 ERROR Compatibility issue ID 'path_hiding'. The 'path_hiding'
   general configuration parameter is set to True, but the configuration generated by ARouteServer for
   OpenBGPD does not support path-hiding mitigation techniques.
   ARouteServer 2017-03-23 21:39:45,955 ERROR One or more compatibility issues have been found.

   Please check the errors reported above for more details.
   To ignore those errors, use the '--ignore-issues' command line argument and list the IDs of the
   issues you want to ignore.
   $ arouteserver openbgpd --ignore-issues path_hiding
   AS 999
   router-id 192.0.2.2

   fib-update no
   log updates
   ...
