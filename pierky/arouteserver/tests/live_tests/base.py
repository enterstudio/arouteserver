# Copyright (C) 2017 Pier Carlo Chiodi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import ipaddr
from jinja2 import Environment, FileSystemLoader
import mock
import os
import time

from docker import InstanceError

from pierky.arouteserver.config.validators import ValidatorPrefixListEntry
from pierky.arouteserver.enrichers.irrdb import IRRDBConfigEnricher_OriginASNs, \
                                                IRRDBConfigEnricher_Prefixes
from pierky.arouteserver.tests.base import ARouteServerTestCase
from pierky.arouteserver.tests.mock_peeringdb import mock_peering_db
from pierky.arouteserver.tests.live_tests.instances import BGPSpeakerInstance


class LiveScenario(ARouteServerTestCase):
    """An helper class to run tests for a given scenario.
    
    This class must be derived by scenario-specific classes that
    must:

    - set the ``MODULE_PATH`` attribute to ``__file__``, in order
      to correctly locate files needed by the scenario.

    - fill the ``INSTANCES`` list with a list of 
      :class:`BGPSpeakerInstance`
      (or derived) instances representing all the BGP speakers involved in the
      scenario.

    - set the ``SHORT_DESCR`` with a short description of the
      scenario; it will be used to print tests description in the
      format "<SHORT_DESCR>: <test function docstring>".

    - fill the ``DATA`` dictionary with IP prefixes IDs that
      represent all the IP addresses used by the scenario; this
      is useful to decouple real IP addresses from what they
      represent or are used to and to have a single definition
      of the tests functions and scenario configuration that can
      be used for both IPv4 and IPv6 tests.

      Example::

        DATA = {
            "rs_IPAddress": "192.0.2.2",
            "AS1_IPAddress": "192.0.2.11",
            "AS1_allowed_prefixes": "1.0.0.0/8",
            "AS1_good_prefix": "1.0.1.0/24",
            "AS101_prefixes": "101.0.0.0/8"
        }

    - optionally, if it's needed by the scenario, the derived classes
      must also fill the ``AS_SET`` and ``R_SET`` dictionaries with
      the expected content of any expanded AS-SETs used in IRRDB
      validation:

      - ``AS_SET``'s items must be in the format
        ``<AS_SET_name>: <list_of_authorized_origin_ASNs>``.

      - ``R_SET``'s items must be in the format
        ``<AS_SET_name>: <list_of_authorized_prefix_IDs>`` (where prefix
        IDs are those reported in the ``DATA`` dictionary).

      Example::

        AS_SET = {
            "AS-AS1": [1],
            "AS-AS1_CUSTOMERS": [101],
            "AS-AS2": [2],
            "AS-AS2_CUSTOMERS": [101]
        }
        R_SET = {
            "AS-AS1": [
                "AS1_allowed_prefixes"
            ],
            "AS-AS1_CUSTOMERS": [
                "AS101_prefixes"
            ]
        }

    - implement the ``set_instance_variables`` method, used to set
      local instance attributes for the instances used within the
      tests functions.

      Example::

        def set_instance_variables(self):
            self.AS1 = self._get_instance_by_name("AS1")
            self.AS2 = self._get_instance_by_name("AS2")
            self.AS131073 = self._get_instance_by_name("AS131073")
            self.rs = self._get_instance_by_name("rs")

    Set the ``__test__`` attribute of derived classes to False to avoid them
    to be used directly by ``nose`` to run tests; only the specific IPv4/IPv6
    class (the one where the ``DATA`` dictionary is set) must have
    ``__test__`` == True.
    """

    MODULE_PATH = None
    SHORT_DESCR = ""

    DATA = {}
    AS_SET = {}
    R_SET = {}
    INSTANCES = []

    DEBUG = False
    DO_NOT_STOP_INSTANCES = False

    CONFIG_BUILDER_CLASS = None

    @classmethod
    def _get_module_dir(cls):
        return os.path.dirname(cls.MODULE_PATH)

    @classmethod
    def _get_local_file_path(cls, filename):
        return os.path.join(cls._get_module_dir(), filename)

    @classmethod
    def _get_instance_by_name(cls, name):
        for instance in cls.INSTANCES:
            if instance.name == name:
                return instance
        raise Exception("Instance not found: {}.".format(name))

    @classmethod
    def _create_var_dir(cls):
        var_dir = "{}/var".format(cls._get_module_dir())
        if not os.path.exists(var_dir):
            os.mkdir(var_dir)
        return var_dir

    @classmethod
    def _do_not_stop_instances(cls):
        return cls.DO_NOT_STOP_INSTANCES or "REUSE_INSTANCES" in os.environ

    @classmethod
    def _do_not_run_instances(cls):
        return "BUILD_ONLY" in os.environ

    @classmethod
    def build_other_cfg(cls, tpl_name):
        """Builds configuration files for BGP speakers which are not the route server.

        Args:
            tpl_name (str): the name of the Jinja2 template file
                relative to the scenario directory.

        Returns:
            the path of the local rendered file.

        To render the template, one attribute is used and consumed by Jinja2:

        - ``data``, the scenario's ``DATA`` dictionary.

        The resulting file is saved into the local ``var`` directory
        and its absolute path is returned.
        """
        cls.debug("Building config from {}/{}".format(
            cls._get_module_dir(), tpl_name))

        env = Environment(
            loader=FileSystemLoader(cls._get_module_dir()),
            trim_blocks=True,
            lstrip_blocks=True
        )
        tpl = env.get_template(tpl_name)
        cfg = tpl.render(data=cls.DATA)

        var_dir = cls._create_var_dir()
        cfg_file_path = "{}/{}.config".format(var_dir, tpl_name)

        with open(cfg_file_path, "w") as f:
            f.write(cfg)

        return cfg_file_path

    @classmethod
    def build_rs_cfg(cls, tpl_dir_name, tpl_name, out_file_name, ip_ver,
                      cfg_general="general.yml", cfg_bogons="bogons.yml",
                      cfg_clients="clients.yml", cfg_roas=None, **kwargs):
        """Builds configuration file for the route server.

        Args:
            tpl_dir_name (str): the directory where Jinja2
                templates are located, relative to the current scenario.

            tpl_name (str): the name of the template to be
                rendered.

            out_file_name (str): the name of the destination
                file.

            ip_ver (int): the IP version for which this route server
                will operate. Use None if the configuration is valid
                for both IPv4 and IPv6.

            cfg_general (str), cfg_bogons (str), cfg_clients (str): the
                name of the 3 main files containing route server's
                options and policies, clients definition and bogons
                IP addresses. File names are relative to the scenario
                directory.

            cfg_roas (str): name of the file containing
                ROAs - used to populate fake RPKI table.

        Returns:
            the path of the local rendered file.

        The resulting file is saved into the local ``var`` directory
        and its absolute path is returned.
        """

        cls.debug("Building config from {}/{}".format(
            tpl_dir_name, tpl_name)
        )

        var_dir = cls._create_var_dir()

        builder = cls.CONFIG_BUILDER_CLASS(
            template_dir="{}/{}".format(cls._get_module_dir(), tpl_dir_name),
            template_name=tpl_name,
            cache_dir=var_dir,
            cfg_general="{}/{}".format(cls._get_module_dir(), cfg_general),
            cfg_bogons="{}/{}".format(cls._get_module_dir(), cfg_bogons),
            cfg_clients="{}/{}".format(cls._get_module_dir(), cfg_clients),
            cfg_roas="{}/{}".format(cls._get_module_dir(), cfg_roas) if cfg_roas else None,
            ip_ver=ip_ver,
            ignore_errors=["*"],
            live_tests=True,
            **kwargs
        )

        cfg_file_path = "{}/{}".format(var_dir, out_file_name)

        with open(cfg_file_path, "w") as f:
            cfg = builder.render_template(f)

        return cfg_file_path

    @classmethod
    def use_static_file(cls, local_filename):
        """Prepare the local file in order to use it later.

        Args:
            filename (str): the name of the local file,
                relative to the scenario directory.

        Returns:
            the path of the file to be used
        """

        var_dir = cls._create_var_dir()
        var_path = os.path.join(var_dir, local_filename)
        local_path = os.path.join(cls._get_module_dir(), local_filename)
        with open(local_path, "r") as src:
            with open(var_path, "w") as dst:
                dst.write(src.read())
        return var_path

    @classmethod
    def mock_irrdb(cls):
    
        def add_prefix_to_list(prefix_name, lst):
            obj = ipaddr.IPNetwork(cls.DATA[prefix_name])
            lst.append(
                ValidatorPrefixListEntry().validate({
                    "prefix": str(obj.ip),
                    "length": obj.prefixlen,
                    "comment": prefix_name
                })
            )

        def _mock_ASSet(self):
            self.prepare()
            for as_set_id in self.builder.as_sets:
                as_set = self.builder.as_sets[as_set_id]
                as_set_name = as_set["name"]
                if as_set_name in cls.AS_SET:
                    as_set["asns"].extend(cls.AS_SET[as_set_name])

        def _mock_RSet(self):
            self.prepare()
            for as_set_id in self.builder.as_sets:
                as_set = self.builder.as_sets[as_set_id]
                as_set_name = as_set["name"]
                if as_set_name in cls.R_SET:
                    for prefix_name in cls.R_SET[as_set_name]:
                        add_prefix_to_list(prefix_name, as_set["prefixes"])

        mock_ASSet = mock.patch.object(
            IRRDBConfigEnricher_OriginASNs, "enrich", autospec=True
        ).start()
        mock_ASSet.side_effect = _mock_ASSet

        mock_RSet = mock.patch.object(
            IRRDBConfigEnricher_Prefixes, "enrich", autospec=True
        ).start()
        mock_RSet.side_effect = _mock_RSet

    @classmethod
    def _setUpClass(cls):
        cls.info("{}: setting instances up...".format(cls.SHORT_DESCR))

        mock_peering_db(cls._get_module_dir() + "/peeringdb_data")
        cls.mock_irrdb()
        cls._setup_instances()

        if cls._do_not_run_instances():
            cls.debug("Skipping starting instances")
            return

        try:
            for instance in cls.INSTANCES:
                instance.set_var_dir("{}/var".format(cls._get_module_dir()))

                if cls._do_not_stop_instances() and instance.is_running():
                    cls.debug("Instance '{}' already running, reloading config".format(instance.name))
                    if not instance.reload_config():
                        raise InstanceError("An error occurred while reloading '{}' configuration.".format(instance.name))
                    continue

                cls.debug("Starting instance '{}'...".format(instance.name))
                instance.start()
        except:
            cls.tearDownClass()
            raise

    @classmethod
    def _tearDownClass(cls):
        mock.patch.stopall()

        if cls._do_not_run_instances():
            cls.debug("Skipping stopping instances")
            return

        if cls._do_not_stop_instances():
            cls.debug("Skipping stopping instances")
            return

        cls.info("{}: stopping instances...".format(cls.SHORT_DESCR))

        for instance in cls.INSTANCES:
            cls.debug("Stopping instance '{}'...".format(instance.name))
            instance.stop()

    def set_instance_variables(self):
        raise NotImplementedError()

    def _setUp(self):
        if self._do_not_run_instances():
            self.skipTest("Build only")

        self.set_instance_variables()

    def receive_route(self, inst, prefix, other_inst=None, as_path=None,
                      next_hop=None, std_comms=None, lrg_comms=None,
                      ext_comms=None, filtered=None, only_best=None,
                      reject_reason=None):
        """Test if the BGP speaker receives the expected route(s).

        If no routes matching the given criteria are found, the
        ``TestCase.fail()`` method is called and the test fails.

        Args:
            inst: the :class:`BGPSpeakerInstance` instance where the routes
                are searched on.

            prefix (str): the IPv4/IPv6 prefix of the routes to search for.

            other_inst: if given, only routes received from this
                :class:`BGPSpeakerInstance` instance are considered.

            as_path (str): if given, only routes with this AS_PATH are
                considered.

            next_hop: can be a string or a :class:`BGPSpeakerInstance`
                instance; if given, only routes that have a NEXT_HOP
                address matching this one are considered.

            std_comms, lrg_comms, ext_comms (list): if given, only routes
                that carry these BGP communities are considered. Use an
                empty list ([]) to consider only routes with no BGP comms.

            filtered (bool): if given, only routes that have been (not)
                filtered are considered.

            only_best (bool): if given, only best routes are considered.

            reject_reason (int): valid only if `filtered` is True: if given
                the route must be reject with this reason code.
                It can be also a set of codes: in this case, the route must
                be rejected with one of those codes.
                Currently implemented on OpenBGPD only.

                Valid codes follow:

                - 1   invalid AS_PATH length
                - 2   prefix is bogon
                - 3   prefix is in global blacklist
                - 4   invalid AFI
                - 5   invalid NEXT_HOP
                - 6   invalid left-most ASN
                - 7   invalid ASN in AS_PATH
                - 8   transit-free ASN in AS_PATH
                - 9   origin ASN not in IRRDB AS-SETs
                - 10  IPv6 prefix not in global unicast space
                - 11  prefis is in client blacklist
                - 12  prefix not in IRRDB AS-SETs
                - 13  invalid prefix length

        """
        assert isinstance(inst, BGPSpeakerInstance), \
            "inst must be of class BGPSpeakerInstance"

        try:
            prefix_ip = ipaddr.IPNetwork(prefix)
        except:
            raise AssertionError("prefix must be a valid IPv4/IPv6 prefix")

        if other_inst:
            assert isinstance(other_inst, BGPSpeakerInstance), \
                "other_inst must be of class BGPSpeakerInstance"

        if as_path:
            try:
                if not isinstance(as_path, str):
                    raise AssertionError()
                for asn in as_path.split(" "):
                    assert asn.strip().isdigit()
            except:
                raise AssertionError("as_path must be a string in the format "
                                     "'<asn1> <asn2>' with <asnX> positive "
                                     "integers")

        next_hop_ip = None
        if next_hop:
            assert isinstance(next_hop, (str, BGPSpeakerInstance)), \
                ("next_hop must be a string representing one IP address or "
                 "a BGPSpeakerInstance object")
            next_hop_ip = next_hop if isinstance(next_hop, str) else next_hop.ip
            try:
                ip = ipaddr.IPAddress(next_hop_ip)
            except:
                raise AssertionError("Invalid next_hop IP address: {}".format(
                    next_hop_ip
                ))

        if std_comms:
            assert isinstance(std_comms, list), \
                ("std_comms must be a list of strings representing "
                 "BGP standard communities")

        if ext_comms:
            assert isinstance(ext_comms, list), \
                ("ext_comms must be a list of strings representing "
                 "BGP extended communities")

        if lrg_comms:
            assert isinstance(lrg_comms, list), \
                ("lrg_comms must be a list of strings representing "
                 "BGP large communities")

        if reject_reason is not None and not filtered:
            raise AssertionError(
                "reject_reason can be set only if filtered is True"
            )

        reject_reasons = None
        if reject_reason is not None:
            if isinstance(reject_reason, int):
                reject_reasons = [reject_reason]
            else:
                reject_reasons = list(reject_reason)
            for code in reject_reasons:
                assert code in range(1,14), "invalid reject_reason"

        include_filtered = filtered if filtered is not None else False
        best_only = only_best if only_best is not None else False

        routes = inst.get_routes(prefix,
                                 include_filtered=include_filtered,
                                 only_best=best_only)

        errors = []
        if not routes:
            errors.append("{inst} does not receive {prefix} at all.")
        else:
            for route in routes:
                err = False
                if other_inst and route.via != other_inst.ip:
                    errors.append("{{inst}} receives {{prefix}} from {via} and not from {{other_inst}}.".format(via=route.via))
                    err = True
                if as_path and route.as_path != as_path:
                    errors.append("{{inst}} receives {{prefix}} with AS_PATH {as_path} and not with {{as_path}}.".format(as_path=route.as_path))
                    err = True
                if next_hop_ip and route.next_hop != next_hop_ip:
                    errors.append("{{inst}} receives {{prefix}} with NEXT_HOP {next_hop} and not with {{next_hop_ip}}.".format(next_hop=route.next_hop))
                    err = True
                if std_comms is not None and sorted(route.std_comms) != sorted(std_comms):
                    errors.append("{{inst}} receives {{prefix}} with std comms {comms} and not with {{std_comms}}.".format(comms=route.std_comms))
                    err = True
                if lrg_comms is not None and sorted(route.lrg_comms) != sorted(lrg_comms):
                    errors.append("{{inst}} receives {{prefix}} with lrg comms {comms} and not with {{lrg_comms}}.".format(comms=route.lrg_comms))
                    err = True
                if ext_comms is not None and sorted(route.ext_comms) != sorted(ext_comms):
                    errors.append("{{inst}} receives {{prefix}} with ext comms {comms} and not with {{ext_comms}}.".format(comms=route.ext_comms))
                    err = True
                if filtered is not None and route.filtered != filtered:
                    errors.append(
                        "{{inst}} receives {{prefix}} from {via}, AS_PATH {as_path}, NEXT_HOP {next_hop} "
                        "but it is {filtered_status} while it is expected to be {filtered_exp}.".format(
                            via=route.via,
                            as_path=route.as_path,
                            next_hop=route.next_hop,
                            filtered_status="filtered" if route.filtered else "not filtered",
                            filtered_exp="filtered" if filtered else "not filtered"
                        )
                    )
                    err = True
                if filtered is True and route.filtered and \
                    reject_reasons is not None and route.reject_reason is not None and \
                    route.reject_reason not in reject_reasons:
                    errors.append(
                        "{{inst}} receives {{prefix}} from {via}, AS_PATH {as_path}, NEXT_HOP {next_hop}, "
                        "it is filtered but reject reasons don't match: it is {reason} while "
                        "it is expected to be {exp_reason}.".format(
                            via=route.via,
                            as_path=route.as_path,
                            next_hop=route.next_hop,
                            reason=route.reject_reason,
                            exp_reason=reject_reasons[0] if len(reject_reasons) == 1 else
                                       "one of {}".format(", ".join(map(str, reject_reasons)))
                        )
                    )
                    err = True
                if not err:
                    return

        if errors:
            criteria = []
            if other_inst:
                criteria.append("from {} ({})".format(other_inst.ip, other_inst.name))
            if as_path:
                criteria.append("with AS_PATH {}".format(as_path))
            if next_hop_ip:
                criteria.append("with next-hop {}".format(next_hop_ip))
            if std_comms:
                criteria.append("with std comms {}".format(std_comms))
            if lrg_comms:
                criteria.append("with lrg comms {}".format(lrg_comms))
            if ext_comms:
                criteria.append("with ext comms {}".format(ext_comms))
            if filtered is True:
                criteria.append("filtered")
            if reject_reasons:
                if len(reject_reasons) == 1:
                    criteria.append(
                        "with reject reason {}".format(reject_reasons[0])
                    )
                else:
                    criteria.append(
                        "with reject reason in {}".format(
                            ", ".join(map(str, reject_reasons))
                        )
                    )

            failure = "Routes not found.\n"
            failure += "Looking for {prefix} on {inst} {criteria}:\n\t".format(
                prefix=prefix,
                inst=inst.name,
                criteria=", ".join(criteria)
            )
            failure += "\n\t".join([
                err.format(
                    inst=inst.name,
                    prefix=prefix,
                    other_inst="{} ({})".format(other_inst.ip, other_inst.name) if other_inst else "",
                    as_path=as_path,
                    next_hop_ip=next_hop_ip,
                    std_comms=std_comms,
                    lrg_comms=lrg_comms,
                    ext_comms=ext_comms,
                ) for err in errors
            ])
            self.fail(failure)

    def log_contains(self, inst, msg, instances={}):
        """Test if the BGP speaker's log contains the expected message.

        This only works for BGP speaker instances that support message
        logging: currently only BIRD.

        If no log entries are found, the ``TestCase.fail()`` method is
        called and the test fails.

        Args:

            inst: the :class:`BGPSpeakerInstance` instance where the
                expected message is searched on.

            msg (str): the text that is expected to be found within
                BGP speaker's log.

            instances (dict): a dictionary of pairs
                "<macro>: <BGPSpeakerInstance>" used to expand macros on
                the *msg* argument. Macros are expanded using the BGP
                speaker's specific client ID or protocol name.

        Example
        ---------

        Given *self.rs* the instance of the route server, and *self.AS1* the
        instance of one of its clients, the following code expands the "{AS1}"
        macro using the BGP speaker specific name for the instance *self.AS1*
        and then looks for it within the route server's log:

            ``self.log_contains(self.rs, "{AS1} bad ASN", {"AS1": self.AS1})``

        On BIRD, "{AS1}" will be expanded using the "protocol name" that BIRD
        uses to identify the BGP session with AS1.
        """
        if not inst.MESSAGE_LOGGING_SUPPORT:
            return

        expanded_msg = msg

        macros_dict = {}
        for inst_name in instances:
            other_inst = instances[inst_name]
            # BAD THING: using a BIRD specific method to understand
            # what's the other instance's name on 'inst'.
            proto_name = inst.get_protocol_name_by_ip(other_inst.ip)
            macros_dict[inst_name] = proto_name

        if macros_dict:
            expanded_msg = expanded_msg.format(**macros_dict)

        if not inst.log_contains(expanded_msg):
            self.fail("Expected message not found on {} logs:\n\t{}".format(inst.name, expanded_msg))

    def session_exists(self, inst_a, inst_b_or_ip):
        """Test if a BGP session between the two instances exists.

        Args:
            inst_a: the :class:`BGPSpeakerInstance` instance where the
                BGP session is looked for.

            inst_b_or_ip: the :class:`BGPSpeakerInstance` instance or an
                IP address that *inst_a* is expected to peer with.
        """

        if inst_a.get_bgp_session(inst_b_or_ip) is None:
            self.fail("A BGP session between '{}' ({}) and '{}' "
                "does not exist.".format(
                inst_a.name, inst_a.ip,
                "{} ({})".format(
                    inst_b_or_ip.name, inst_b_or_ip.ip
                ) if isinstance(inst_b_or_ip, BGPSpeakerInstance)
                  else inst_b_or_ip
            ))

    def session_is_up(self, inst_a, inst_b):
        """Test if a BGP session between the two instances is up.

        If a BGP session between the two instances is not up, the
        ``TestCase.fail()`` method is called and the test fails.

        Args:
            inst_a: the :class:`BGPSpeakerInstance` instance where the
                BGP session is looked for.

            inst_b: the :class:`BGPSpeakerInstance` instance that *inst_a* is
                expected to peer with.
        """

        self.session_exists(inst_a, inst_b)

        if inst_a.bgp_session_is_up(inst_b):
            return
        time.sleep(5)
        if inst_a.bgp_session_is_up(inst_b, force_update=True):
            return
        self.fail("BGP session between '{}' ({}) and '{}' ({}) is not up.".format(
            inst_a.name, inst_a.ip, inst_b.name, inst_b.ip
        ))
