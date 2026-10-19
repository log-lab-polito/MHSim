"""Build an instrumented probe copy of an AnyLogic reference model.

The forklift-parity work needs evidence about how AnyLogic's Material Handling
Library actually moves transporters: positions at a fine time step, the phase of
the line-guided controller tick, and the times of the fleet callbacks. This
module copies `anylogic/Model N/` to a separate folder, renames the copy so the
IDE never confuses it with the reference model (the two would otherwise share a
`_BUILD` folder and a Java package), and injects probe code that only uses the
documented AnyLogic API:

* `MHLBlock_xjal.getSettings()` with `MHLSettings.lineGuidedUpdateTimestep` and
  `MHLSettings.lineGuidedUpdateEvent.getRest()` for the controller tick phase;
* `Agent.ext(TransporterExtension.class)` for state, distance travelled and the
  effective speed limits;
* the `TransporterFleet` callbacks (`onSeize`, `onRelease`,
  `onDestinationReached`, `onEnterNode`, `onExitNode`, `onEnterPath`,
  `onExitPath`, `onTransporterStateChanged`);
* optionally `MHLLogger.DEBUG` for the library's own `EventExecutor` log.

The reference model and its exports are never written. The probe writes one CSV
per run to `<out-dir>/out/` with the columns
`kind,t,unit,x,y,z,rotation,distance_m,state,moving,tick_rest,speed,info`, where
`kind` is `META`, `SAMPLE`, an event name, or `END`. Positions are in AnyLogic
presentation units (pixels); `distance_m` is the transporter's cumulative
distance in metres; `tick_rest` is the model time left until the next
line-guided controller update; `speed` is `Agent.getSpeed()`.

Run from the repository root, for example::

    python -m scripts.anylogic_probe --model 1 --sim-param arrival_rate_s=60.01 --mhl-debug
    python -m scripts.anylogic_probe --model 5
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import xml.dom.minidom
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANYLOGIC_DIR = REPO_ROOT / "anylogic"
DEFAULT_OUT_DIR = Path("/private/tmp/mhsim_probe")
FLEET_NAME = "forklifts_fleet"
MHL = "com.anylogic.libraries.material_handling."
# Ids for injected elements. The reference models use 13-digit ids; this range is unused.
ID_BASE = 1999000000000

FLEET_CALLBACKS = {
    "onSeize": 'probe_line("SEIZE", unit, "agent=" + agent);',
    "onRelease": 'probe_line("RELEASE", unit, "agent=" + agent);',
    "onDestinationReached": 'probe_line("ARRIVE", unit, "");',
    "onEnterNode": 'probe_line("ENTER_NODE", unit, "node=" + node.getName());',
    "onExitNode": 'probe_line("EXIT_NODE", unit, "node=" + node.getName());',
    "onEnterPath": 'probe_line("ENTER_PATH", unit, "path=" + path.getName());',
    "onExitPath": 'probe_line("EXIT_PATH", unit, "path=" + path.getName());',
    "onTransporterStateChanged": 'probe_line("STATE", unit, "state=" + state);',
}

_CELL = ('(cell == null ? "none" : "rack " + cell.getRack() + " bay " + cell.getBay() + " shelf " + cell.getShelf()'
         ' + " deep " + cell.getDeepPosition() + " xyz " + cell.getX() + " " + cell.getY() + " " + cell.getZ())')


def _with_unit(kind: str, info: str) -> str:
    return f'probe_line("{kind}", unit, {info});'


def _every_unit(kind: str, info: str) -> str:
    """For callbacks without a transporter argument: one line per fleet transporter."""
    return f"for (Agent _u : {FLEET_NAME}) probe_line(\"{kind}\", _u, {info});"


# Callbacks of process blocks, keyed by model and embedded object name. Argument
# names follow the block signatures in the shipped Javadoc.
def _move_by_transporter(prefix: str) -> dict:
    return {
        "onEnter": _every_unit(f"{prefix}_ENTER", '"agent=" + agent'),
        "onSeizeTransporter": _with_unit(f"{prefix}_SEIZE", '"agent=" + agent'),
        "onLoadingStarted": _with_unit(f"{prefix}_LOAD_START", '"agent=" + agent'),
        "onLoadingFinished": _with_unit(f"{prefix}_LOAD_END", '"agent=" + agent'),
        "onUnloadingStarted": _with_unit(f"{prefix}_UNLOAD_START", '"agent=" + agent'),
        "onUnloadingFinished": _with_unit(f"{prefix}_UNLOAD_END", '"agent=" + agent'),
        "onReleaseTransporter": _with_unit(f"{prefix}_RELEASE", '"agent=" + agent'),
        "onExit": _every_unit(f"{prefix}_EXIT", '"agent=" + agent'),
    }


BLOCK_CALLBACKS = {
    2: {
        "moveToStorage": _move_by_transporter("STORE"),
        "moveToOutbound": _move_by_transporter("RETRIEVE"),
        "delay": {
            "onEnter": _every_unit("DELAY_ENTER", '"agent=" + agent + ";delayTime=" + delayTime'),
        },
    },
    5: {
        "store": {
            "onEnter": _every_unit("STORE_ENTER", '"agent=" + agent'),
            "onSeizeTransporter": _with_unit("STORE_SEIZE", '"agent=" + agent'),
            "onLoadingStart": _with_unit("STORE_LOAD_START", '"agent=" + agent'),
            "onLoadingFinished": _with_unit("STORE_LOAD_END", '"agent=" + agent'),
            "onStorageStart": _with_unit(
                "STORE_STORAGE_START", f'"agent=" + agent + ";storingTime=" + storingTime + ";cell=" + {_CELL}'
            ),
            "onStorageFinished": _every_unit("STORE_STORAGE_END", '"agent=" + agent'),
            "onReleaseTransporter": _with_unit("STORE_RELEASE", '"agent=" + agent'),
            "onExit": _every_unit("STORE_EXIT", f'"agent=" + agent + ";cell=" + {_CELL}'),
        },
        "retrieve": {
            "onEnter": _every_unit("RETRIEVE_ENTER", f'"agent=" + agent + ";cell=" + {_CELL}'),
            "onSeizeTransporter": _with_unit("RETRIEVE_SEIZE", '"agent=" + agent'),
            "onRetrievalStart": _with_unit(
                "RETRIEVE_RETRIEVAL_START",
                f'"agent=" + agent + ";retrievingTime=" + retrievingTime + ";cell=" + {_CELL}',
            ),
            "onRetrievalFinished": _every_unit("RETRIEVE_RETRIEVAL_END", '"agent=" + agent'),
            "onUnloadingStart": _with_unit("RETRIEVE_UNLOAD_START", '"agent=" + agent'),
            "onUnloadingFinished": _with_unit("RETRIEVE_UNLOAD_END", '"agent=" + agent'),
            "onReleaseTransporter": _with_unit("RETRIEVE_RELEASE", '"agent=" + agent'),
            "onExit": _every_unit("RETRIEVE_EXIT", '"agent=" + agent'),
        },
        "delay": {
            "onEnter": _every_unit("DELAY_ENTER", '"agent=" + agent + ";delayTime=" + delayTime'),
        },
    },
}


def _cdata(code: str) -> str:
    if "]]>" in code:
        raise ValueError("probe code must not contain ']]>'")
    return f"<![CDATA[{code}]]>"


def _matching_end(text: str, start: int, tag: str) -> int:
    """Return the index just past the `</tag>` that closes the `<tag>` at `start`."""
    pattern = re.compile(rf"<{tag}[\s>]|</{tag}>")
    depth = 0
    for match in pattern.finditer(text, start):
        if match.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return match.end()
        else:
            depth += 1
    raise ValueError(f"unbalanced <{tag}>")


def _main_class_span(text: str) -> tuple[int, int]:
    match = re.search(
        r"<ActiveObjectClass>\s*<Id>\d+</Id>\s*<Name><!\[CDATA\[Main\]\]></Name>", text
    )
    if not match:
        raise ValueError("Main agent type not found")
    return match.start(), _matching_end(text, match.start(), "ActiveObjectClass")


def _own_section(text: str, span: tuple[int, int], tag: str) -> int:
    """Index just past `<tag>` of Main's own section (before any nested agent type)."""
    start, end = span
    nested = text.find("<ActiveObjectClass>", start + 1, end)
    limit = nested if nested != -1 else end
    idx = text.find(f"<{tag}>", start, limit)
    if idx == -1:
        raise ValueError(f"Main has no own <{tag}> section")
    return idx + len(tag) + 2


def _java(out_dir: Path, tag: str, sample_dt: float, sample_until: float, mhl_debug: bool) -> dict:
    out = (out_dir / "out").as_posix()
    debug = ""
    if mhl_debug:
        debug = f"""
	{MHL}MHLLogger.DEBUG = true;
	{MHL}MHLLogger.addClass({MHL}EventExecutor.class);
	System.setOut(new java.io.PrintStream(new java.io.FileOutputStream(new java.io.File(_probeDir, _probeName.replace(".csv", "_stdout.txt"))), true));"""
    startup = f"""// --- MHSim probe (injected by scripts/anylogic_probe.py) ---
try {{
	java.io.File _probeDir = new java.io.File("{out}");
	_probeDir.mkdirs();
	String _probeName = String.format("{tag}_%s_%06d.csv", new java.text.SimpleDateFormat("yyyyMMdd_HHmmss").format(new java.util.Date()), System.nanoTime() % 1000000);
	probe_out = new java.io.PrintWriter(new java.io.BufferedWriter(new java.io.FileWriter(new java.io.File(_probeDir, _probeName))));
	probe_out.println("kind,t,unit,x,y,z,rotation,distance_m,state,moving,tick_rest,speed,info");
	{MHL}MHLSettings _ps = {FLEET_NAME}.getSettings();
	probe_line("META", null, "lineGuidedUpdateTimestep=" + _ps.lineGuidedUpdateTimestep + ";freeSpaceUpdateTimestep=" + _ps.freeSpaceUpdateTimestep + ";sampleDt={sample_dt!r};sampleUntil={sample_until!r}");{debug}
}} catch (Exception _probeEx) {{
	traceln("MHSim probe: could not open its output file: " + _probeEx);
	probe_out = null;
}}
// --- end MHSim probe ---
"""
    sampler = f"""if (time() == 0) {{
	for (Agent _u : {FLEET_NAME}) {{
		{MHL}TransporterExtension _x = _u.ext({MHL}TransporterExtension.class);
		probe_line("META", _u, "maxSpeed=" + _x.getMaximumSpeed(com.anylogic.engine.SpeedUnits.MPS)
			+ ";accel=" + _x.getAcceleration(com.anylogic.engine.AccelerationUnits.MPS_SQ)
			+ ";decel=" + _x.getDeceleration(com.anylogic.engine.AccelerationUnits.MPS_SQ)
			+ ";maxSpeedCurved=" + _x.getMaximumSpeedOnCurvedSegment(com.anylogic.engine.SpeedUnits.MPS)
			+ ";nav=" + _x.getNavigationType()
			+ ";home=" + _x.getHomeX() + " " + _x.getHomeY() + " " + _x.getHomeZ()
			+ ";cargo=" + _x.getCargoPosition());
	}}
}}
if (time() <= {sample_until!r}) {{
	for (Agent _u : {FLEET_NAME}) probe_line("SAMPLE", _u, "");
}}"""
    line = f"""if (probe_out == null) return;
{MHL}MHLSettings _ps = {FLEET_NAME}.getSettings();
double _tr = (_ps != null && _ps.lineGuidedUpdateEvent.isActive()) ? _ps.lineGuidedUpdateEvent.getRest() : Double.NaN;
String _info = info == null ? "" : info.replace(',', ' ');
if (u == null) {{
	probe_out.println(String.format(java.util.Locale.ROOT, "%s,%.9f,,,,,,,,,%.9f,,%s", kind, time(), _tr, _info));
}} else {{
	{MHL}TransporterExtension _x = u.ext({MHL}TransporterExtension.class);
	probe_out.println(String.format(java.util.Locale.ROOT, "%s,%.9f,%d,%.9f,%.9f,%.9f,%.9f,%.9f,%s,%b,%.9f,%.9f,%s",
		kind, time(), System.identityHashCode(u), u.getX(), u.getY(), u.getZ(), u.getRotation(),
		_x == null ? Double.NaN : _x.getDistanceTravelled(com.anylogic.engine.LengthUnits.METER),
		_x == null ? "" : String.valueOf(_x.getState()), u.isMoving(), _tr, u.getSpeed(), _info));
}}
if (!kind.equals("SAMPLE") || time() - Math.floor(time()) < {sample_dt!r} / 2) probe_out.flush();"""
    destroy = """
// --- MHSim probe ---
if (probe_out != null) {
	probe_line("END", null, "");
	probe_out.close();
	probe_out = null;
}
System.out.flush();"""
    return {"startup": startup, "sampler": sampler, "line": line, "destroy": destroy}


def _variable_xml() -> str:
    return f"""
				<Variable Class="PlainVariable">
					<Id>{ID_BASE + 1}</Id>
					<Name><![CDATA[probe_out]]></Name>
					<X>20</X><Y>950</Y>
					<Label><X>10</X><Y>0</Y></Label>
					<PublicFlag>false</PublicFlag>
					<PresentationFlag>true</PresentationFlag>
					<ShowLabel>true</ShowLabel>
					<Properties SaveInSnapshot="false" Constant="false" AccessType="public" StaticVariable="false">
						<Type><![CDATA[java.io.PrintWriter]]></Type>
						<InitialValue Class="CodeValue">
							<Code><![CDATA[null]]></Code>
						</InitialValue>
					</Properties>
				</Variable>"""


def _event_xml(action: str, sample_dt: float) -> str:
    return f"""
				<Event>
					<Id>{ID_BASE + 2}</Id>
					<Name><![CDATA[probe_sampler]]></Name>
					<X>20</X><Y>970</Y>
					<Label><X>10</X><Y>0</Y></Label>
					<PublicFlag>false</PublicFlag>
					<PresentationFlag>true</PresentationFlag>
					<ShowLabel>true</ShowLabel>
					<Properties TriggerType="timeout" Mode="cyclic">
						<Timeout Class="CodeUnitValue">
							<Code><![CDATA[1]]></Code>
							<Unit Class="TimeUnits"><![CDATA[SECOND]]></Unit>
						</Timeout>
						<Rate Class="CodeUnitValue">
							<Code><![CDATA[1]]></Code>
							<Unit Class="RateUnits"><![CDATA[PER_SECOND]]></Unit>
						</Rate>
						<Id>{ID_BASE + 3}</Id>
						<OccurrenceAtTime>true</OccurrenceAtTime>
						<OccurrenceDate>1769500800000</OccurrenceDate>
						<OccurrenceTime Class="CodeUnitValue">
							<Code><![CDATA[0]]></Code>
							<Unit Class="TimeUnits"><![CDATA[SECOND]]></Unit>
						</OccurrenceTime>
						<RecurrenceCode Class="CodeUnitValue">
							<Code><![CDATA[{sample_dt!r}]]></Code>
							<Unit Class="TimeUnits"><![CDATA[SECOND]]></Unit>
						</RecurrenceCode>
						<Condition><![CDATA[false]]></Condition>
					</Properties>
					<Action>{_cdata(action)}</Action>
				</Event>"""


def _function_xml(body: str) -> str:
    return f"""
				<Function AccessType="default" StaticFunction="false">
					<ReturnModificator>VOID</ReturnModificator>
					<ReturnType><![CDATA[double]]></ReturnType>
					<Id>{ID_BASE + 4}</Id>
					<Name><![CDATA[probe_line]]></Name>
					<X>20</X><Y>990</Y>
					<Label><X>10</X><Y>0</Y></Label>
					<PublicFlag>false</PublicFlag>
					<PresentationFlag>true</PresentationFlag>
					<ShowLabel>true</ShowLabel>
					<Parameter>
						<Name><![CDATA[kind]]></Name>
						<Type><![CDATA[String]]></Type>
					</Parameter>
					<Parameter>
						<Name><![CDATA[u]]></Name>
						<Type><![CDATA[Agent]]></Type>
					</Parameter>
					<Parameter>
						<Name><![CDATA[info]]></Name>
						<Type><![CDATA[String]]></Type>
					</Parameter>
					<Body>{_cdata(body)}</Body>
				</Function>"""


def _patch_callbacks(text: str, block: str, callbacks: dict[str, str]) -> str:
    fleet = re.search(rf"<EmbeddedObject>\s*<Id>\d+</Id>\s*<Name><!\[CDATA\[{block}\]\]></Name>", text)
    if not fleet:
        raise ValueError(f"embedded object {block} not found")
    fleet_end = _matching_end(text, fleet.start(), "EmbeddedObject")
    for name, probe in callbacks.items():
        param = re.compile(
            rf"<Parameter>\s*<Name><!\[CDATA\[{name}\]\]></Name>\s*"
            rf"(?:<Value Class=\"CodeValue\">\s*<Code><!\[CDATA\[(?P<code>.*?)\]\]></Code>\s*</Value>\s*)?</Parameter>",
            re.S,
        )
        match = param.search(text, fleet.start(), fleet_end)
        if not match:
            raise ValueError(f"{block}.{name} not found")
        code = probe + ("\n" + match.group("code") if match.group("code") else "")
        replacement = (
            f"<Parameter>\n\t\t\t\t\t\t\t<Name><![CDATA[{name}]]></Name>\n"
            f'\t\t\t\t\t\t\t<Value Class="CodeValue">\n\t\t\t\t\t\t\t\t<Code>{_cdata(code)}</Code>\n'
            f"\t\t\t\t\t\t\t</Value>\n\t\t\t\t\t\t</Parameter>"
        )
        delta = len(replacement) - (match.end() - match.start())
        text = text[: match.start()] + replacement + text[match.end() :]
        fleet_end += delta
    return text


def _set_sim_params(text: str, values: dict[str, str], real_time_scale: float | None) -> str:
    start = text.find("<SimulationExperiment")
    if start == -1:
        raise ValueError("Simulation experiment not found")
    end = text.find("</SimulationExperiment>", start)
    block = text[start:end]
    for name, value in values.items():
        param = re.compile(
            rf"(<ParameterName><!\[CDATA\[{re.escape(name)}\]\]></ParameterName>\s*<ParameterValue Class=\"CodeValue\">\s*<Code><!\[CDATA\[)(.*?)(\]\]></Code>)",
            re.S,
        )
        block, count = param.subn(lambda m: m.group(1) + value + m.group(3), block, count=1)
        if count != 1:
            # A blank parameter keeps the agent default; give it an explicit value.
            blank = re.compile(
                rf"(<ParameterName><!\[CDATA\[{re.escape(name)}\]\]></ParameterName>)(\s*</Parameter>)",
                re.S,
            )
            value_xml = (
                '\n\t\t\t\t\t<ParameterValue Class="CodeValue">\n'
                f"\t\t\t\t\t\t<Code><![CDATA[{value}]]></Code>\n"
                "\t\t\t\t\t</ParameterValue>"
            )
            block, count = blank.subn(lambda m: m.group(1) + value_xml + m.group(2), block, count=1)
        if count != 1:
            raise ValueError(f"Simulation parameter {name} not found")
    if real_time_scale is not None:
        block, count = re.subn(
            r"<RealTimeScale>[^<]*</RealTimeScale>", f"<RealTimeScale>{real_time_scale!r}</RealTimeScale>", block
        )
        if count != 1:
            raise ValueError("RealTimeScale not found")
    return text[:start] + block + text[end:]


def build_probe(model: int, out_dir: Path, sample_dt: float, sample_until: float, mhl_debug: bool,
                sim_params: dict[str, str], real_time_scale: float | None, suffix: str = "") -> Path:
    source = ANYLOGIC_DIR / f"Model {model}"
    alp = source / f"Model {model}.alp"
    probe_name = f"Model {model} Probe" + (f" {suffix}" if suffix else "")
    package = f"model_{model}"
    probe_package = f"model_{model}_probe" + (f"_{suffix.lower()}" if suffix else "")
    target = out_dir / probe_name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(f"Model {model}.alp", "*.txt"))
    for export in source.glob("*.txt"):
        (target / export.name).write_text("")

    text = alp.read_text(encoding="utf-8")
    text, renamed = re.subn(rf"(<Model>\s*<Id>\d+</Id>\s*<Name><!\[CDATA\[)Model {model}(\]\]></Name>)",
                            rf"\g<1>{probe_name}\g<2>", text, count=1)
    if renamed != 1:
        raise ValueError("model name not found")
    text = text.replace(f"<![CDATA[{package}]]>", f"<![CDATA[{probe_package}]]>")

    java = _java(out_dir, probe_package, sample_dt, sample_until, mhl_debug)
    span = _main_class_span(text)
    start_code = text.find("<StartupCode><![CDATA[", span[0], span[1])
    if start_code == -1:
        raise ValueError("Main has no startup code")
    insert = start_code + len("<StartupCode><![CDATA[")
    text = text[:insert] + java["startup"] + text[insert:]

    span = _main_class_span(text)
    destroy = re.compile(r"<DestroyCode><!\[CDATA\[(.*?)\]\]></DestroyCode>", re.S).search(text, span[0], span[1])
    if not destroy:
        raise ValueError("Main has no destroy code")
    text = text[: destroy.end(1)] + java["destroy"] + text[destroy.end(1) :]

    for section, xml_text in (
        ("Variables", _variable_xml()),
        ("Events", _event_xml(java["sampler"], sample_dt)),
        ("Functions", _function_xml(java["line"])),
    ):
        span = _main_class_span(text)
        idx = _own_section(text, span, section)
        text = text[:idx] + xml_text + text[idx:]

    text = _patch_callbacks(text, FLEET_NAME, FLEET_CALLBACKS)
    for block, callbacks in BLOCK_CALLBACKS.get(model, {}).items():
        text = _patch_callbacks(text, block, callbacks)
    if sim_params or real_time_scale is not None:
        text = _set_sim_params(text, sim_params, real_time_scale)

    xml.dom.minidom.parseString(text.encode("utf-8"))  # fail early on malformed XML
    out_alp = target / f"{probe_name}.alp"
    out_alp.write_text(text, encoding="utf-8")
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    return out_alp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=int, required=True, choices=(1, 2, 5))
    parser.add_argument("--suffix", default="", help="name suffix for a second probe variant, e.g. Stoch")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-dt", type=float, default=0.01, help="sampling interval in seconds")
    parser.add_argument("--sample-until", type=float, default=600.0, help="stop sampling after this model time")
    parser.add_argument("--mhl-debug", action="store_true", help="enable MHLLogger debug output for EventExecutor")
    parser.add_argument("--sim-param", action="append", default=[], metavar="NAME=VALUE",
                        help="override a Simulation experiment parameter (repeatable)")
    parser.add_argument("--real-time-scale", type=float, default=None)
    args = parser.parse_args(argv)

    out_dir = args.out_dir.resolve()
    if REPO_ROOT in out_dir.parents or out_dir == REPO_ROOT:
        parser.error("--out-dir must be outside the repository")
    sim_params = dict(item.split("=", 1) for item in args.sim_param)
    if args.suffix and not args.suffix.isalnum():
        parser.error("--suffix must be alphanumeric")
    out_alp = build_probe(args.model, out_dir, args.sample_dt, args.sample_until, args.mhl_debug,
                          sim_params, args.real_time_scale, args.suffix)
    print(f"probe model: {out_alp}")
    print(f"probe output: {out_dir / 'out'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
