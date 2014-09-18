# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Portions Copyright Buildbot Team Members
# Original Copyright (c) 2010 The Chromium Authors.

"""Simple JSON exporter."""

import datetime
import re
from twisted.python import log

from twisted.internet import defer
from twisted.web import html, resource, server

from buildbot.status.buildrequest import BuildRequestStatus
from buildbot.status.web.base import HtmlResource, path_to_root, map_branches, getCodebasesArg, getRequestCharset, getResultsArg
import json


_IS_INT = re.compile(r'^[-+]?\d+$')

FLAGS = """\
  - as_text
    - By default, application/json is used. Setting as_text=1 change the type
      to text/plain and implicitly sets compact=0 and filter=1. Mainly useful to
      look at the result in a web browser.
  - compact
    - By default, the json data is compact and defaults to 1. For easier to read
      indented output, set compact=0.
  - select
    - By default, most children data is listed. You can do a random selection
      of data by using select=<sub-url> multiple times to coagulate data.
      "select=" includes the actual url otherwise it is skipped.
  - numbuilds
    - By default, only in memory cached builds are listed. You can as for more data
      by using numbuilds=<number>.
  - filter
    - Filters out null, false, and empty string, list and dict. This reduce the
      amount of useless data sent.
  - callback
    - Enable uses of JSONP as described in
      http://en.wikipedia.org/wiki/JSONP. Note that
      Access-Control-Allow-Origin:* is set in the HTTP response header so you
      can use this in compatible browsers.
  - codebases
    - Filter builds by the codebases they use an example of this is:
      unity_branch=trunk&cellsdk_branch=default
      Note: You will probably need to specify all of the codebases.
  - results
    - Filter builds by the build results. For example:
      results=0&results=7
      will only return the build where the result is either 0 or 7.

"""

EXAMPLES = """\
  - /json
    - Root node, that *doesn't* mean all the data. Many things (like logs) must
      be explicitly queried for performance reasons.
  - /json/builders/
    - All builders.
  - /json/builders/<A_BUILDER>
    - A specific builder as compact text.
  - /json/builders/<A_BUILDER>/builds
    - All *cached* builds.
  - /json/builders/<A_BUILDER>/builds/_all
    - All builds. Warning, reads all previous build data. (Can be filtered by codebases)
  - /json/builders/<A_BUILDER>/builds/<A_BUILD>
    - Where <A_BUILD> is either positive, a build number, or negative, a past
      build. Using <4 will give the last 4 builds.
  - /json/builders/<A_BUILDER>/builds/-1/source_stamp/changes
    - Build changes
  - /json/builders/<A_BUILDER>/builds?select=-1&select=-2
    - Two last builds on '<A_BUILDER>' builder.
  - /json/builders/<A_BUILDER>/builds?select=-1/source_stamp/changes&select=-2/source_stamp/changes
    - Changes of the two last builds on '<A_BUILDER>' builder.
  - /json/builders/<A_BUILDER>/slaves
    - Slaves associated to this builder.
  - /json/builders/<A_BUILDER>?select=&select=slaves
    - Builder information plus details information about its slaves. Neat eh?
  - /json/slaves/<A_SLAVE>
    - A specific slave.
  - /json/slaves/<A_SLAVE>/builds
    - The current builds on a specific slave
  - /json/slaves/<A_SLAVE>/builds/<15
    - The last 15 builds built on a specific slave
  - /json?select=slaves/<A_SLAVE>/&select=project&select=builders/<A_BUILDER>/builds/<A_BUILD>
    - A selection of random unrelated stuff as an random example. :)
  - /json/projects/
    - All projects
  - /json/projects/<A_PROJECT>
    - A specific project.
  - /json/projects/<A_PROJECT>/<A_BUILDER>
    - A specific builder on a project.
  - /json/buildqueue/
    - The current build queue
  - /json/pending/<A_BUILDER>/
    - The current pending builds for a builder (Can be filtered by codebases)
  - /json/globalstatus/
    - Global information about the current builds and slaves in use
"""


def RequestArg(request, arg, default):
    return request.args.get(arg, [default])[0]


def RequestArgToBool(request, arg, default):
    value = RequestArg(request, arg, default)
    if value in (False, True):
        return value
    value = value.lower()
    if value in ('1', 'true'):
        return True
    if value in ('0', 'false'):
        return False
        # Ignore value.
    return default


def FilterOut(data):
    """Returns a copy with None, False, "", [], () and {} removed.
    Warning: converts tuple to list."""
    if isinstance(data, (list, tuple)):
        # Recurse in every items and filter them out.
        items = map(FilterOut, data)
        if not filter(lambda x: not x in ('', False, None, [], {}, ()), items):
            return None
        return items
    elif isinstance(data, dict):
        return dict(filter(lambda x: not x[1] in ('', False, None, [], {}, ()),
                           [(k, FilterOut(v)) for (k, v) in data.iteritems()]))
    else:
        return data


class JsonResource(resource.Resource):
    """Base class for json data."""

    contentType = "application/json"
    cache_seconds = 60
    help = None
    pageTitle = None
    level = 0

    def __init__(self, status):
        """Adds transparent lazy-child initialization."""
        resource.Resource.__init__(self)
        # buildbot.status.builder.Status
        self.status = status

    def getChildWithDefault(self, path, request):
        """Adds transparent support for url ending with /"""
        if path == "" and len(request.postpath) == 0:
            return self
        if path == 'help' and self.help:
            pageTitle = ''
            if self.pageTitle:
                pageTitle = self.pageTitle + ' help'
            return HelpResource(self.help,
                                pageTitle=pageTitle,
                                parent_node=self)
            # Equivalent to resource.Resource.getChildWithDefault()
        if path in self.children:
            return self.children[path]
        return self.getChild(path, request)

    def putChild(self, name, res):
        """Adds the resource's level for help links generation."""

        def RecurseFix(res, level):
            res.level = level + 1
            for c in res.children.itervalues():
                RecurseFix(c, res.level)

        RecurseFix(res, self.level)
        resource.Resource.putChild(self, name, res)

    def render_GET(self, request):
        """Renders a HTTP GET at the http request level."""
        d = defer.maybeDeferred(lambda: self.content(request))

        def handle(data):
            if isinstance(data, unicode):
                data = data.encode("utf-8")
            request.setHeader("Access-Control-Allow-Origin", "*")
            if RequestArgToBool(request, 'as_text', False):
                request.setHeader("content-type", 'text/plain')
            else:
                request.setHeader("content-type", self.contentType)
                # Make sure we get fresh pages.
            if self.cache_seconds:
                now = datetime.datetime.utcnow()
                expires = now + datetime.timedelta(seconds=self.cache_seconds)
                request.setHeader("Expires",
                                  expires.strftime("%a, %d %b %Y %H:%M:%S GMT"))
                request.setHeader("Pragma", "no-cache")
            return data

        d.addCallback(handle)

        def ok(data):
            try:
                request.write(data)
                request.finish()
            except RuntimeError:
                log.msg("Connection from {0} lost".format(request.client.host))

        def fail(f):
            request.processingFailed(f)
            return None # processingFailed will log this for us

        d.addCallbacks(ok, fail)
        return server.NOT_DONE_YET

    @defer.inlineCallbacks
    def content(self, request):
        """Renders the json dictionaries."""
        # Supported flags.
        select = request.args.get('select')
        as_text = RequestArgToBool(request, 'as_text', False)
        filter_out = RequestArgToBool(request, 'filter', as_text)
        compact = RequestArgToBool(request, 'compact', not as_text)
        callback = request.args.get('callback')

        # Implement filtering at global level and every child.
        if select is not None:
            del request.args['select']
            # Do not render self.asDict()!
            data = {}
            # Remove superfluous /
            select = [s.strip('/') for s in select]
            select.sort(cmp=lambda x, y: cmp(x.count('/'), y.count('/')),
                        reverse=True)
            for item in select:
                # Start back at root.
                node = data
                # Implementation similar to twisted.web.resource.getChildForRequest
                # but with a hacked up request.
                child = self
                prepath = request.prepath[:]
                postpath = request.postpath[:]
                request.postpath = filter(None, item.split('/'))
                while request.postpath and not child.isLeaf:
                    pathElement = request.postpath.pop(0)
                    node[pathElement] = {}
                    node = node[pathElement]
                    request.prepath.append(pathElement)
                    child = child.getChildWithDefault(pathElement, request)

                # some asDict methods return a Deferred, so handle that
                # properly
                if hasattr(child, 'asDict'):
                    child_dict = yield defer.maybeDeferred(lambda: child.asDict(request))
                else:
                    child_dict = {
                        'error': 'Not available',
                    }
                node.update(child_dict)

                request.prepath = prepath
                request.postpath = postpath
        else:
            data = yield defer.maybeDeferred(lambda: self.asDict(request))

        if filter_out:
            data = FilterOut(data)
        if compact:
            data = json.dumps(data, separators=(',', ':'))
        else:
            data = json.dumps(data, sort_keys=True, indent=2)
        if callback:
            # Only accept things that look like identifiers for now
            callback = callback[0]
            if re.match(r'^[a-zA-Z$_][a-zA-Z$0-9._]*$', callback):
                data = '%s(%s);' % (callback, data)
        defer.returnValue(data)

    @defer.inlineCallbacks
    def asDict(self, request):
        """Generates the json dictionary.

        By default, renders every childs."""
        if self.children:
            data = {}
            for name in self.children:
                child = self.getChildWithDefault(name, request)
                if isinstance(child, JsonResource):
                    data[name] = yield defer.maybeDeferred(lambda:
                    child.asDict(request))
                    # else silently pass over non-json resources.
            defer.returnValue(data)
        else:
            raise NotImplementedError()


def ToHtml(text):
    """Convert a string in a wiki-style format into HTML."""
    indent = 0
    in_item = False
    output = []
    for line in text.splitlines(False):
        match = re.match(r'^( +)\- (.*)$', line)
        if match:
            if indent < len(match.group(1)):

                indent = len(match.group(1))

            elif indent > len(match.group(1)):

                while indent > len(match.group(1)):
                    #output.append('</ul>')

                    output.append('<br/><br/>')
                    indent -= 2

                    #if in_item:

                    # Close previous item
                    #output.append('</li>')
                    #output.append('<li>')
            in_item = True
            line = match.group(2)

        elif indent:
            if line.startswith((' ' * indent) + '  '):
                # List continuation
                line = line.strip()
                output.append('<br>')
            else:
                # List is done
                if in_item:
                    #output.append('</li>')
                    in_item = False
                while indent > 0:
                    #output.append('</div>')
                    indent -= 2

        if line.startswith('/'):
            if not '?' in line:
                line_full = line + '?as_text=1'
            else:
                line_full = line + '&as_text=1'
            output.append('<a href="' + html.escape(line_full) + '">' +
                          html.escape(line) + '</a>')
        else:
            output.append(html.escape(line).replace('  ', '&nbsp;&nbsp;'))
        if not in_item:
            output.append('<br>')

            #if in_item:
            #output.append('</li>')
    while indent > 0:
        #output.append('</div>')
        indent -= 2
    return '\n'.join(output)


class HelpResource(HtmlResource):
    def __init__(self, text, pageTitle, parent_node):
        HtmlResource.__init__(self)
        self.text = text
        self.pageTitle = pageTitle
        self.parent_level = parent_node.level
        self.parent_children = parent_node.children.keys()

    def content(self, request, cxt):
        cxt['level'] = self.parent_level
        cxt['text'] = ToHtml(self.text)
        cxt['children'] = [n for n in self.parent_children if n != 'help']
        cxt['flags'] = ToHtml(FLAGS)
        cxt['examples'] = ToHtml(EXAMPLES).replace(
            'href="/json',
            'href="%s' % path_to_root(request) + 'json')

        template = request.site.buildbot_service.templates.get_template("jsonhelp.html")
        return template.render(**cxt)


class BuilderPendingBuildsJsonResource(JsonResource):
    help = """Describe pending builds for a builder.
"""
    pageTitle = 'Builder'

    def __init__(self, status, builder_status):
        JsonResource.__init__(self, status)
        self.builder_status = builder_status

    def asDict(self, request):
        # buildbot.status.builder.BuilderStatus
        d = self.builder_status.getPendingBuildRequestStatuses()

        def to_dict(statuses):
            return defer.gatherResults(
                [b.asDict_async() for b in statuses])

        d.addCallback(to_dict)
        return d


class BuilderJsonResource(JsonResource):
    help = """Describe a single builder.
"""
    pageTitle = 'Builder'

    def __init__(self, status, builder_status):
        JsonResource.__init__(self, status)
        self.builder_status = builder_status
        self.putChild('builds', BuildsJsonResource(status, builder_status))
        self.putChild('slaves', BuilderSlavesJsonResources(status,
                                                           builder_status))
        self.putChild(
            'pendingBuilds',
            BuilderPendingBuildsJsonResource(status, builder_status))

    def asDict(self, request):
        # buildbot.status.builder.BuilderStatus
        return self.builder_status.asDict_async()


class BuildersJsonResource(JsonResource):
    help = """List of all the builders defined on a master.
"""
    pageTitle = 'Builders'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        for builder_name in self.status.getBuilderNames():
            self.putChild(builder_name,
                          BuilderJsonResource(status,
                                              status.getBuilder(builder_name)))


class BuilderSlavesJsonResources(JsonResource):
    help = """Describe the slaves attached to a single builder.
"""
    pageTitle = 'BuilderSlaves'

    def __init__(self, status, builder_status):
        JsonResource.__init__(self, status)
        self.builder_status = builder_status
        for slave_name in self.builder_status.slavenames:
            self.putChild(slave_name,
                          SlaveJsonResource(status,
                                            self.status.getSlave(slave_name)))


class BuildJsonResource(JsonResource):
    help = """Describe a single build.
"""
    pageTitle = 'Build'

    def __init__(self, status, build_status):
        JsonResource.__init__(self, status)
        self.build_status = build_status
        # TODO: support multiple sourcestamps
        sourcestamp = build_status.getSourceStamps()[0]
        self.putChild('source_stamp',
                      SourceStampJsonResource(status, sourcestamp))
        self.putChild('steps', BuildStepsJsonResource(status, build_status))

    def asDict(self, request):
        return self.build_status.asDict(request)


class AllBuildsJsonResource(JsonResource):
    help = """All the builds that were run on a builder.
"""
    pageTitle = 'AllBuilds'

    def __init__(self, status, builder_status):
        JsonResource.__init__(self, status)
        self.builder_status = builder_status

    def getChild(self, path, request):
        # Dynamic childs.
        if isinstance(path, int) or _IS_INT.match(path):
            build_status = self.builder_status.getBuild(int(path))
            if build_status:
                return BuildJsonResource(self.status, build_status)
        elif "<" in path:
            try:
                num = int(path.replace("<", ""))
            except ValueError:
                #Defaults to last 15
                num = 15

            return PastBuildsJsonResource(self.status, num, builder_status=self.builder_status)

        return JsonResource.getChild(self, path, request)

    def asDict(self, request):
        results = {}
        #Get codebases
        codebases = {}
        getCodebasesArg(request=request, codebases=codebases)
        results_filter = getResultsArg(request)

        # If max > buildCacheSize, it'll trash the cache...
        cache_size = self.builder_status.master.config.caches['Builds']
        max = int(RequestArg(request, 'max', cache_size))
        for i in range(0, max):
            child = self.getChildWithDefault(-i, request)
            if not isinstance(child, BuildJsonResource):
                continue

            if len(codebases) != 0 and \
                    not child.build_status.builder.foundCodebasesInBuild(child.build_status, codebases):
                continue

            if results_filter is not None and \
                child.build_status.results not in results_filter:
                continue

            results[child.build_status.getNumber()] = child.asDict(request)

        return results


class PastBuildsJsonResource(JsonResource):
    help = """Previous x number of builds that were run on a builder."""
    pageTitle = 'Builds'

    def __init__(self, status, number, builder_status=None, slave_status=None):
        JsonResource.__init__(self, status)
        self.builder_status = builder_status
        self.number = number
        self.slave_status = slave_status

    def asDict(self, request):
        #Get codebases
        if self.builder_status is not None:
            codebases = {}
            getCodebasesArg(request=request, codebases=codebases)
            encoding = getRequestCharset(request)
            branches = [b.decode(encoding) for b in request.args.get("branch", []) if b]
            results = getResultsArg(request)

            builds = list(self.builder_status.generateFinishedBuilds(branches=map_branches(branches),
                                                              codebases=codebases,
                                                              results=results,
                                                              num_builds=self.number))

            return [b.asDict(request) for b in builds]

        if self.slave_status is not None:
            n = 0
            slavename = self.slave_status.getName()
            recent_builds = []

            my_builders = []
            for bname in self.status.getBuilderNames():
                b = self.status.getBuilder(bname)
                for bs in b.getSlaves():
                    if bs.getName() == slavename:
                        my_builders.append(b)

            for rb in self.status.generateFinishedBuilds(builders=[b.getName() for b in my_builders]):
                if rb.getSlavename() == slavename:
                    n += 1
                    recent_builds.append(rb.asDict(request=request))
                    if n > self.number:
                        return recent_builds

            return recent_builds


class BuildsJsonResource(AllBuildsJsonResource):
    help = """Builds that were run on a builder.
"""
    pageTitle = 'Builds'

    def __init__(self, status, builder_status):
        AllBuildsJsonResource.__init__(self, status, builder_status)
        self.putChild('_all', AllBuildsJsonResource(status, builder_status))

    def getChild(self, path, request):
        # Transparently redirects to _all if path is not ''.
        return self.children['_all'].getChildWithDefault(path, request)

    def asDict(self, request):
        #Get codebases
        codebases = {}
        getCodebasesArg(request=request, codebases=codebases)

        builds = self.builder_status.getCachedBuilds(codebases=codebases)
        return [b.asDict() for b in builds]


class BuildStepJsonResource(JsonResource):
    help = """A single build step.
"""
    pageTitle = 'BuildStep'

    def __init__(self, status, build_step_status):
        # buildbot.status.buildstep.BuildStepStatus
        JsonResource.__init__(self, status)
        self.build_step_status = build_step_status
        # TODO self.putChild('logs', LogsJsonResource())

    def asDict(self, request):
        return self.build_step_status.asDict()


class BuildStepsJsonResource(JsonResource):
    help = """A list of build steps that occurred during a build.
"""
    pageTitle = 'BuildSteps'

    def __init__(self, status, build_status):
        JsonResource.__init__(self, status)
        self.build_status = build_status
        # The build steps are constantly changing until the build is done so
        # keep a reference to build_status instead

    def getChild(self, path, request):
        # Dynamic childs.
        build_step_status = None
        if isinstance(path, int) or _IS_INT.match(path):
            build_step_status = self.build_status.getSteps()[int(path)]
        else:
            steps_dict = dict([(step.getName(), step)
                               for step in self.build_status.getSteps()])
            build_step_status = steps_dict.get(path)
        if build_step_status:
            # Create it on-demand.
            child = BuildStepJsonResource(self.status, build_step_status)
            # Cache it.
            index = self.build_status.getSteps().index(build_step_status)
            self.putChild(str(index), child)
            self.putChild(build_step_status.getName(), child)
            return child
        return JsonResource.getChild(self, path, request)

    def asDict(self, request):
        # Only use the number and not the names!
        results = {}
        index = 0
        for step in self.build_status.getSteps():
            results[index] = step.asDict(request)
            index += 1
        return results


class ChangeJsonResource(JsonResource):
    help = """Describe a single change that originates from a change source.
"""
    pageTitle = 'Change'

    def __init__(self, status, change):
        # buildbot.changes.changes.Change
        JsonResource.__init__(self, status)
        self.change = change

    def asDict(self, request):
        return self.change.asDict()


class ChangesJsonResource(JsonResource):
    help = """List of changes.
"""
    pageTitle = 'Changes'

    def __init__(self, status, changes):
        JsonResource.__init__(self, status)
        for c in changes:
            # c.number can be None or clash another change if the change was
            # generated inside buildbot or if using multiple pollers.
            if c.number is not None and str(c.number) not in self.children:
                self.putChild(str(c.number), ChangeJsonResource(status, c))
            else:
                # Temporary hack since it creates information exposure.
                self.putChild(str(id(c)), ChangeJsonResource(status, c))

    def asDict(self, request):
        """Don't throw an exception when there is no child."""
        if not self.children:
            return {}
        return JsonResource.asDict(self, request)


class ChangeSourcesJsonResource(JsonResource):
    help = """Describe a change source.
"""
    pageTitle = 'ChangeSources'

    def asDict(self, request):
        result = {}
        n = 0
        for c in self.status.getChangeSources():
            # buildbot.changes.changes.ChangeMaster
            change = {}
            change['description'] = c.describe()
            result[n] = change
            n += 1
        return result


class ProjectJsonResource(JsonResource):
    help = """Project-wide settings.
"""
    pageTitle = 'Project'

    def asDict(self, request):
        return self.status.asDict()


class ProjectsJsonResource(JsonResource):
    help = """List the registered projects.
"""
    pageTitle = 'Projects'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        for project_name, project_status in status.getProjects().iteritems():
            self.putChild(project_name, SingleProjectJsonResource(status, project_status))


class SingleProjectJsonResource(JsonResource):
    help = """Describe a project in katana"""
    pageTitle = 'Project'

    def __init__(self, status, project_status):
        JsonResource.__init__(self, status)
        self.status = status
        self.project_status = project_status
        self.name = self.project_status.name
        self.setup_children(status, project_status)

    def setup_children(self, status, project):
        builder_names = self.status.getBuilderNamesByProject(self.project_status.name)
        for b in builder_names:
            builder = self.status.getBuilder(b)
            self.putChild(b, SingleProjectBuilderJsonResource(status, builder))

    @defer.inlineCallbacks
    def asDict(self, request):
        from buildbot.status.web.base import path_to_comparison
        result = {'builders': []}

        #Get codebases
        codebases = {}
        getCodebasesArg(request=request, codebases=codebases)
        encoding = getRequestCharset(request)
        branches = [branch.decode(encoding) for branch in request.args.get("branch", []) if branch]

        result['comparisonURL'] = path_to_comparison(request, self.project_status.name, codebases)

        defers = []
        for name in self.children:
            child = self.getChildWithDefault(name, request)
            d = child.asDict(request, codebases, branches, True)
            defers.append(d)

        for d in defers:
            r = yield d
            result['builders'].append(r)

        defer.returnValue(result)


class SingleProjectBuilderJsonResource(JsonResource):
    """
    Returns  a single builder for a project JSON with
    latestBuild info
    """

    def __init__(self, status, builder):
        JsonResource.__init__(self, status)
        self.builder = builder

    @defer.inlineCallbacks
    def builder_dict(self, builder, codebases, request, branches, base_build_dict):
        d = yield builder.asDict_async(codebases, request, base_build_dict)

        #Get latest build
        builds = list(builder.generateFinishedBuilds(branches=map_branches(branches),
                                                     codebases=codebases,
                                                     num_builds=1, max_search=200, useCache=True))

        if len(builds) > 0:
            d['latestBuild'] = builds[0].asBaseDict(request, include_artifacts=True, include_failure_url=True)

        defer.returnValue(d)

    @defer.inlineCallbacks
    def asDict(self, request, codebases=None, branches=None, base_build_dict=False):
        if codebases is None or branches is None:
            #Get codebases
            codebases = {}
            getCodebasesArg(request=request, codebases=codebases)
            encoding = getRequestCharset(request)
            branches = [branch.decode(encoding) for branch in request.args.get("branch", []) if branch]

        builder_dict = yield self.builder_dict(self.builder, codebases, request, branches, base_build_dict)
        defer.returnValue(builder_dict)


class QueueJsonResource(JsonResource):
    help = """List the builds in the queue."""
    pageTitle = 'Queue'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        self.status = status

    @defer.inlineCallbacks
    def asDict(self, request):
        unclaimed_brq = yield self.status.master.db.buildrequests.getUnclaimedBuildRequest(sorted=True)

        #Convert to dictionary
        output = []
        defers = []
        for br_dict in unclaimed_brq:
            br = BuildRequestStatus(br_dict['buildername'], br_dict['brid'], self.status)
            d = br.asDict_async()
            defers.append(d)

        #Call the yield after to run async calls
        for d in defers:
            r = yield d
            output.append(r)

        defer.returnValue(output)


class PendingBuildsJsonResource(JsonResource):
    help = """List the builds in the queue for a particular builder."""
    pageTitle = 'Queue'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        self.status = status
        for builder_name in self.status.getBuilderNames():
            self.putChild(builder_name,
                          SinglePendingBuildsJsonResource(status,
                                              status.getBuilder(builder_name)))


class SinglePendingBuildsJsonResource(JsonResource):
    help = """List the pending builds for a specific builder."""
    pageTitle = 'Queue'

    def __init__(self, status, builder):
        JsonResource.__init__(self, status)
        self.status = status
        self.builder = builder

    @defer.inlineCallbacks
    def asDict(self, request):
        builds = yield self.builder.getPendingBuildRequestStatuses()

        #Get codebases
        codebases = {}
        getCodebasesArg(request=request, codebases=codebases)

        #Filter + add sort info
        pending = []
        for br in builds:
            result = True
            if len(codebases) > 0:
                from buildbot.status.web.builder import foundCodebasesInPendingBuild
                result = yield foundCodebasesInPendingBuild(br, codebases)


            if result:
                br.sort_value = yield br.getSubmitTime()
                pending.append(br)

        def sort_queue(br, otherBR):
            return br.sort_value - otherBR.sort_value

        pending = sorted(pending, cmp=sort_queue)

        #Convert to dictionary
        output = []
        for b in pending:
            d = yield b.asDict_async(request)
            output.append(d)

        defer.returnValue(output)


class SlaveBuildsJsonResource(JsonResource):
    help = """List builds related with a slave."""
    pageTitle = 'Slave Builds'

    def __init__(self, status, slave_status):
        JsonResource.__init__(self, status)
        self.slave_status = slave_status
        self.name = self.slave_status.getName()

    def getChild(self, path, request):
        # Dynamic childs.
        if "<" in path:
            try:
                num = int(path.replace("<", ""))
            except ValueError:
                #Defaults to last 15
                num = 15

            return PastBuildsJsonResource(self.status, num, slave_status=self.slave_status)

        return JsonResource.getChild(self, path, request)

    def asDict(self, request):
        slavename = self.slave_status.getName()
        my_builders = []
        for bname in self.status.getBuilderNames():
            b = self.status.getBuilder(bname)
            for bs in b.getSlaves():
                if bs.getName() == slavename:
                    my_builders.append(b)

        current_builds = []
        for b in my_builders:
            for cb in b.getCurrentBuilds():
                if cb.getSlavename() == slavename:
                    current_builds.append(cb.asDict(request))

        return current_builds



class SlaveJsonResource(JsonResource):
    help = """Describe a slave.
"""
    pageTitle = 'Slave'

    def __init__(self, status, slave_status):
        JsonResource.__init__(self, status)
        self.slave_status = slave_status
        self.name = self.slave_status.getName()
        self.builders = None
        self.putChild('builds', SlaveBuildsJsonResource(status, slave_status))

    def getBuilders(self):
        if self.builders is None:
            # Figure out all the builders to which it's attached
            self.builders = []
            for builderName in self.status.getBuilderNames():
                if self.name in self.status.getBuilder(builderName).slavenames:
                    builder_status = self.status.getBuilder(builderName)
                    builderDict = {'name': builderName, 'friendly_name': builder_status.getFriendlyName(),
                           'url': self.status.getURLForThing(builder_status)}
                    self.builders.append(builderDict)
        return self.builders

    def asDict(self, request):
        results = self.slave_status.asDict()
        #Add builder information
        results['builders'] = self.getBuilders()
        return results


class SlavesJsonResource(JsonResource):
    help = """List the registered slaves.
"""
    pageTitle = 'Slaves'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        for slave_name in status.getSlaveNames():
            self.putChild(slave_name,
                          SlaveJsonResource(status,
                                            status.getSlave(slave_name)))


class SourceStampJsonResource(JsonResource):
    help = """Describe the sources for a SourceStamp.
"""
    pageTitle = 'SourceStamp'

    def __init__(self, status, source_stamp):
        # buildbot.sourcestamp.SourceStamp
        JsonResource.__init__(self, status)
        self.source_stamp = source_stamp
        self.putChild('changes',
                      ChangesJsonResource(status, source_stamp.changes))
        # TODO(maruel): Should redirect to the patch's url instead.
        #if source_stamp.patch:
        #  self.putChild('patch', StaticHTML(source_stamp.path))

    def asDict(self, request):
        return self.source_stamp.asDict()


class MetricsJsonResource(JsonResource):
    help = """Master metrics.
"""
    title = "Metrics"

    def asDict(self, request):
        metrics = self.status.getMetrics()
        if metrics:
            return metrics.asDict()
        else:
            # Metrics are disabled
            return None


class GlobalJsonResource(JsonResource):
    help = """Gives information that can be used on all realtime pages"""
    pageTitle = 'Global Info'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        self.slaves = status.getSlaveNames()

    @defer.inlineCallbacks
    def asDict(self, request):
        import time
        connected_slaves = []
        slave_busy = []
        for s in self.slaves:
            ss = self.status.getSlave(s)
            if ss.isConnected:
                connected_slaves.append(s)
            if len(ss.getRunningBuilds()) > 0:
                slave_busy.append(s)

        current_builds = set()
        for b_name in self.status.getBuilderNames():
            b = self.status.getBuilder(b_name)
            current_builds |= set(b.getCurrentBuilds())

        queue = yield self.status.master.db.buildrequests.getUnclaimedBuildRequest(sorted=False)
        result = {"slaves_count": len(connected_slaves),
                  "slaves_busy": len(slave_busy),
                  "running_builds": len(current_builds),
                  "build_load": len(queue) + len(current_builds),
                  "utc": time.time() * 1000}

        defer.returnValue(result)


class JsonStatusResource(JsonResource):
    """Retrieves all json data."""
    help = """JSON status

Root page to give a fair amount of information in the current buildbot master
status. You may want to use a child instead to reduce the load on the server.

For help on any sub directory, use url /child/help
"""
    pageTitle = 'Katana JSON'

    def __init__(self, status):
        JsonResource.__init__(self, status)
        self.level = 1
        self.putChild('builders', BuildersJsonResource(status))
        self.putChild('change_sources', ChangeSourcesJsonResource(status))
        self.putChild('project', ProjectJsonResource(status))
        self.putChild('projects', ProjectsJsonResource(status))
        self.putChild('slaves', SlavesJsonResource(status))
        self.putChild('metrics', MetricsJsonResource(status))
        self.putChild('buildqueue', QueueJsonResource(status))
        self.putChild('pending', PendingBuildsJsonResource(status))
        self.putChild('globalstatus', GlobalJsonResource(status))
        # This needs to be called before the first HelpResource().body call.
        self.hackExamples()

    def content(self, request):
        result = JsonResource.content(self, request)
        # This is done to hook the downloaded filename.
        request.path = 'buildbot'
        return result

    def hackExamples(self):
        global EXAMPLES
        # Find the first builder with a previous build or select the last one.
        builder = None
        for b in self.status.getBuilderNames():
            builder = self.status.getBuilder(b)
            if builder.getBuild(-1):
                break
        if not builder:
            return
        EXAMPLES = EXAMPLES.replace('<A_BUILDER>', builder.getName())
        build = builder.getBuild(-1)
        projects = self.status.getProjects().keys()
        if len(projects) > 0:
            EXAMPLES = EXAMPLES.replace('<A_PROJECT>', projects[0])
        if build:
            EXAMPLES = EXAMPLES.replace('<A_BUILD>', str(build.getNumber()))
        if builder.slavenames:
            EXAMPLES = EXAMPLES.replace('<A_SLAVE>', builder.slavenames[0])

# vim: set ts=4 sts=4 sw=4 et:
