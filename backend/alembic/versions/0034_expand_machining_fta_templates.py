"""Create expanded, operation- and defect-specific V2 machining FTA templates.

Revision ID: 0034_expand_machining_fta_templates
Revises: 0033_fta_recurrence_management

V1 templates and investigation snapshots are preserved. For untouched seeded
V1 templates, this migration adds a richer published V2. Existing custom
revisions are never overwritten or replaced.
"""
from alembic import op
import sqlalchemy as sa
import json
import re

revision = "0034_expand_machining_fta_templates"
down_revision = "0033_fta_recurrence_management"
branch_labels = None
depends_on = None

# Each entry is (cause label, optional expected condition / evidence prompt).
CORE_GROUPS = [
    ("Machine condition", [
        ("Spindle bearing wear, preload or lubrication issue", "Check spindle noise, temperature, vibration trend, bearing history and service limits."),
        ("Spindle / workhead runout or alignment error", "Measure runout with a calibrated indicator at the relevant datum and compare with machine specification."),
        ("Axis backlash, lost motion or positioning error", "Verify backlash, positioning accuracy and repeatability using the machine acceptance method."),
        ("Thermal growth or machine warm-up variation", "Compare cold and stabilised dimensions; review warm-up cycle, ambient temperature and compensation."),
        ("Machine structure, guideway or clamping rigidity", "Check guideway condition, foundation, looseness and vibration under actual cutting load."),
    ]),
    ("Tool and toolholding", [
        ("Wrong tool grade, geometry, diameter or nose radius", "Compare tool identification and measured geometry with the approved tool list and process sheet."),
        ("Tool wear, chipping, built-up edge or edge fracture", "Inspect the cutting edge under magnification and compare wear with tool-life criteria."),
        ("Toolholder, collet, chuck or taper seating defect", "Inspect taper contact, cleanliness, retention force and holder condition."),
        ("Tool runout, projection or stick-out incorrect", "Measure tool runout and projection at the specified gauge length."),
        ("Tool deflection or inadequate tool stiffness", "Compare tool overhang and cutting load with recommended limits; inspect for deflection marks."),
    ]),
    ("Process method and parameters", [
        ("Cutting speed outside approved process window", "Compare actual RPM / surface speed with the approved parameter sheet."),
        ("Feed rate or feed per tooth incorrect", "Compare actual feed with the validated process setting and material/tool recommendation."),
        ("Depth of cut, step-over or finishing allowance incorrect", "Verify roughing and finishing allowances against the operation plan."),
        ("Wrong machining sequence or operation omitted", "Compare actual routing and operation sequence with the approved process flow."),
        ("Incorrect wear offset, geometry offset or compensation entry", "Audit offset values, sign, units and edit history against the setup record."),
        ("Coolant concentration, flow, pressure or direction inadequate", "Check concentration, flow at cutting edge, pressure and coolant condition against standards."),
    ]),
    ("Fixture and workholding", [
        ("Datum locator, stop or locating pin worn / damaged", "Inspect locator dimensions, contact pattern and datum repeatability."),
        ("Fixture seating surface contaminated or damaged", "Check chips, burrs, damage and full seating at every locating contact."),
        ("Clamping force too low, too high or inconsistent", "Measure or verify clamping pressure / torque against the fixture standard."),
        ("Workpiece distortion due to clamping sequence", "Compare free-state and clamped measurements; verify the prescribed clamp sequence."),
        ("Fixture rigidity, support or vibration issue", "Check support points, fixture deflection and vibration during the actual cut."),
    ]),
    ("Material and blank condition", [
        ("Material grade, condition or batch mismatch", "Verify material certificate, heat / batch number and identification against drawing requirements."),
        ("Hardness or heat-treatment variation", "Measure hardness at defined locations and compare with the material specification."),
        ("Casting / forging stock, scale or surface allowance variation", "Inspect incoming stock and compare machining allowance with the drawing and supplier data."),
        ("Residual stress or material movement after stock removal", "Compare dimensions before and after roughing / stress relief and review material history."),
    ]),
    ("Measurement and inspection system", [
        ("Gauge calibration, zero or resolution inadequate", "Check calibration status, zero setting, resolution and uncertainty for the tolerance being measured."),
        ("Wrong gauge, measuring range or measurement method", "Verify instrument selection and method against the control plan."),
        ("Datum, alignment or measurement location inconsistent", "Confirm datum establishment, probe direction and measurement location."),
        ("Temperature, cleanliness or handling affects measurement", "Stabilise component and gauge temperature; clean contact surfaces and repeat measurement."),
        ("Gauge R&R or operator-to-operator variation", "Review MSA / Gauge R&R and compare repeatability and reproducibility with acceptance criteria."),
    ]),
    ("People, setup and program control", [
        ("Wrong part program, revision or machine selected", "Verify program number, revision, machine assignment and approved release status."),
        ("Setup sheet, tool list or work instruction obsolete", "Compare shop-floor documents with the current controlled revision."),
        ("Setup datum, work offset or tool offset entered incorrectly", "Cross-check entered values with setup sheet and first-off verification."),
        ("First-off approval or in-process check missed", "Review inspection records, sign-off and reaction plan at the required frequency."),
        ("Program edit not independently checked or released", "Review edit log, approval and prove-out records for the affected program revision."),
    ]),
]

DEFECT_CAUSES = {
    "DIM-OVERSIZE": ("Oversize-specific checks", [
        ("Finishing tool wear / nose radius change leaves excess diameter", "Measure insert wear and nose radius; compare diameter trend against tool life."),
        ("X-axis / radial wear offset set too positive", "Compare active X wear offset with approved setup value and previous accepted run."),
        ("Wrong tool compensation direction or radius compensation", "Verify compensation mode, direction and active tool geometry in the program."),
        ("Thermal expansion of spindle, tool or workpiece increases cut diameter", "Compare component size at controlled temperature and after machine stabilisation."),
        ("Spring-back or elastic recovery after interrupted / heavy cut", "Compare in-process and post-release diameter; review cutting force and finishing allowance."),
        ("Boring bar / tool deflection changes effective cutting diameter", "Check bar stiffness, overhang and measured deflection under load."),
    ]),
    "DIM-UNDERSIZE": ("Undersize-specific checks", [
        ("Finishing allowance insufficient or roughing cut already undersize", "Measure intermediate diameter before finishing and compare with planned allowance."),
        ("Tool nose / cutting edge geometry causes excess material removal", "Inspect insert geometry and verify programmed tool nose compensation."),
        ("X-axis / radial wear offset set too negative", "Audit active wear offset and compare with the approved offset sheet."),
        ("Tool pull-out, holder movement or insert seating shift", "Check tool clamping, insert seating and witness marks after machining."),
        ("Measurement force or method causes false low reading", "Repeat with a suitable low-force calibrated instrument and an independent method."),
    ]),
    "DIM-LENGTH": ("Length-specific checks", [
        ("Z-axis datum, work offset or tool length reference incorrect", "Verify Z zero, work offset and tool length against the setup master."),
        ("Facing / cutoff tool position or wear offset incorrect", "Measure tool position and compare active offset with setup record."),
        ("Part seating against axial stop inconsistent", "Check stop contact, chip entrapment and axial seating repeatability."),
        ("Cutoff blade deflection or part movement during separation", "Inspect cutoff blade, support and part retention during separation."),
        ("Incorrect program coordinate, endpoint or stock allowance", "Compare programmed endpoint and coordinate system with drawing dimensions."),
    ]),
    "GEO-TAPER": ("Taper-specific checks", [
        ("Tailstock / centre misalignment or workpiece axis misalignment", "Check alignment between spindle axis, tailstock centre and machine axis."),
        ("Workpiece deflection varies along unsupported length", "Compare support arrangement and deflection at multiple positions along the part."),
        ("Tool deflection changes with cutting position", "Review tool overhang, cutting force and diameter trend along the length."),
        ("Spindle / guideway alignment error", "Check machine geometric accuracy and axis alignment records."),
        ("Uneven clamping or support pressure distorts the component", "Measure free-state geometry and verify support / clamping points."),
    ]),
    "GEO-OVALITY": ("Ovality-specific checks", [
        ("Uneven chuck jaw pressure or soft-jaw contact", "Check jaw bore, contact pattern, clamping pressure and component deformation."),
        ("Thin-wall component distortion during clamping", "Compare roundness in clamped and free state using a controlled method."),
        ("Spindle bearing or workholding runout", "Measure spindle nose, chuck and workpiece runout independently."),
        ("Interrupted cutting load or chatter causes lobing", "Review vibration signature, cutting parameters and roundness trace."),
        ("Residual stress release causes post-machining distortion", "Compare geometry after roughing, finishing and stabilisation."),
    ]),
    "GEO-RUNOUT": ("Runout-specific checks", [
        ("Datum axis used for machining differs from inspection datum", "Verify drawing datum scheme and reproduce the same datum axis during inspection."),
        ("Chuck / collet / fixture eccentricity", "Measure fixture reference runout and repeat after re-clamping."),
        ("Part not seated against locating face or axial stop", "Inspect seating face, chips and contact pattern."),
        ("Spindle nose, centre or toolholder runout", "Measure spindle and holder runout separately with calibrated equipment."),
        ("Bending or distortion after unclamping", "Compare runout while clamped and after release."),
    ]),
    "GEO-POSITION": ("Hole-position-specific checks", [
        ("Incorrect work coordinate system or datum pickup", "Verify work offset, probing routine and datum feature used by the program."),
        ("Fixture locating error or locator wear", "Measure locator coordinates and repeatability against fixture drawing."),
        ("CNC axis positioning / squareness error", "Review axis calibration, ballbar or positioning test results."),
        ("Incorrect drilling / milling tool centre compensation", "Audit tool radius, cutter compensation and programmed coordinates."),
        ("Part movement during drilling or milling", "Inspect clamp force, support and witness marks around the feature."),
    ]),
    "GEO-FLATNESS": ("Flatness-specific checks", [
        ("Uneven clamping or unsupported surface during machining", "Compare flatness in clamped and free state; verify support locations."),
        ("Facing cutter / insert height mismatch", "Check insert seating and cutter face runout across the cutting diameter."),
        ("Thermal distortion from cutting heat or coolant imbalance", "Review temperature, coolant delivery and flatness before / after cooling."),
        ("Residual stress released during material removal", "Compare flatness after roughing and finishing; review stock removal sequence."),
        ("Machine table, fixture or spindle face not geometrically true", "Verify reference surface and machine geometry with calibrated instruments."),
    ]),
    "SURF-ROUGH": ("Surface-finish-specific checks", [
        ("Feed marks too large due to feed / nose radius combination", "Compare feed per revolution and tool nose radius with finish calculation."),
        ("Worn, chipped or built-up cutting edge", "Inspect cutting edge and surface for corresponding wear / adhesion pattern."),
        ("Inadequate coolant lubrication or chip evacuation", "Check coolant concentration, direction and chip recutting evidence."),
        ("Tool vibration, overhang or workpiece instability", "Review vibration, tool projection and support stiffness."),
        ("Wrong grinding wheel grade, dressing or surface speed", "For grinding operations, verify wheel specification, dressing and operating speed."),
    ]),
    "SURF-CHATTER": ("Chatter-specific checks", [
        ("Tool / workpiece natural frequency resonance", "Check chatter frequency and test a controlled speed change to identify resonance."),
        ("Excessive tool overhang or low toolholder stiffness", "Measure overhang and compare tool assembly stiffness with recommended limits."),
        ("Workholding or tailstock support insufficient", "Verify clamp force, support pressure and component rigidity."),
        ("Spindle bearing, guideway or fixture vibration", "Compare vibration spectrum at idle and during cutting."),
        ("Cutting speed, feed or depth of cut excites chatter", "Review stable cutting window and controlled parameter trials."),
    ]),
    "BURR": ("Burr-specific checks", [
        ("Tool edge wear / geometry produces excessive exit burr", "Inspect tool edge and identify burr location relative to cutting direction."),
        ("Incorrect feed, speed or depth at breakthrough", "Review breakthrough parameters and tool engagement sequence."),
        ("No chamfer / deburring operation or insufficient allowance", "Verify drawing edge-break requirement and routing operation."),
        ("Tool path leaves sharp intersection at cross-hole or slot", "Inspect intersecting feature geometry and program tool path."),
        ("Deburring tool worn, wrong or incorrectly applied", "Check deburring tool condition, coverage and operator method."),
    ]),
    "THREAD": ("Thread-specific checks", [
        ("Wrong tap / thread mill pitch, form or tolerance class", "Verify tool marking and thread gauge against drawing callout."),
        ("Tap drill diameter or pre-bore size incorrect", "Measure pre-hole diameter and compare with approved thread preparation chart."),
        ("Threading cycle pitch / feed synchronisation incorrect", "Check spindle-feed synchronisation and programmed pitch."),
        ("Tool runout or tap misalignment causes damaged thread", "Check holder alignment, floating holder and entry chamfer."),
        ("Tool wear, chip packing or coolant delivery damages thread", "Inspect tap flutes, chips and coolant delivery at the cutting zone."),
        ("Thread depth, chamfer or start position incorrect", "Verify programmed depth, lead-in and thread runout against drawing."),
    ]),
    "GRIND-BURN": ("Grinding-burn-specific checks", [
        ("Grinding wheel loading, glazing or incorrect grade", "Inspect wheel condition and verify wheel grade / structure for material."),
        ("Dressing interval, dresser condition or dressing depth incorrect", "Review dressing records, dresser wear and dressing parameters."),
        ("Excessive infeed, dwell or spark-out condition", "Compare actual infeed and dwell with validated grinding cycle."),
        ("Coolant flow, concentration or nozzle direction inadequate", "Verify flow at contact zone, concentration and nozzle alignment."),
        ("Wheel speed / work speed combination causes excessive heat", "Compare actual speeds with approved grinding process window."),
        ("Burn not detected due to inadequate inspection method", "Verify etch / nital, Barkhausen or other specified burn inspection method."),
    ]),
    "TOOL-BREAK": ("Tool-breakage-specific checks", [
        ("Tool overload from excessive feed or depth of cut", "Compare actual cutting load and parameters with tool maker limits."),
        ("Interrupted cut, hard spot or unexpected stock condition", "Inspect workpiece stock and review load spike at breakage time."),
        ("Tool collision, wrong approach or unsafe retract path", "Review machine alarm history, tool path and collision / simulation records."),
        ("Tool clamping, insert screw or retention failure", "Inspect screw torque, holder retention and fracture surface."),
        ("Tool life exceeded or replacement interval not followed", "Compare tool usage count and life limit with replacement records."),
        ("Chip entanglement or poor evacuation causes tool overload", "Inspect chip form, evacuation path and coolant / air blast effectiveness."),
    ]),
}

OPERATION_CAUSES = {
    "TURN": ("Turning process checks", [
        ("Workpiece overhang / unsupported length excessive", "Compare chuck projection and tailstock / steady-rest support with setup standard."),
        ("Incorrect chuck jaw bore, grip length or clamping sequence", "Verify jaw contact, grip length and clamping procedure."),
        ("Turning insert orientation, centre height or nose radius incorrect", "Check insert orientation, centre height and tool setup."),
        ("Roughing / finishing stock allowance or pass sequence unsuitable", "Compare pass plan and remaining stock with process sheet."),
    ]),
    "CNC_TURN": ("CNC turning process checks", [
        ("Wrong turret station, tool geometry or offset assignment", "Verify turret station, tool number and geometry / wear offset mapping."),
        ("G-code modal state, work offset or compensation call incorrect", "Audit active G-codes, work offset and tool nose radius compensation."),
        ("CSS / spindle limit or RPM clamp incorrect", "Verify constant surface speed, maximum RPM and actual spindle behaviour."),
        ("Bar feeder, collet or remnant control causes inconsistent projection", "Check bar feed length, collet condition and remnant handling."),
    ]),
    "MILL": ("Milling process checks", [
        ("Cutter runout or unequal insert height", "Measure cutter runout and insert height variation."),
        ("Cutter engagement / step-over creates excessive cutting load", "Compare radial and axial engagement with approved milling strategy."),
        ("Workpiece support allows movement under milling force", "Verify clamp location and support relative to cutting direction."),
        ("Climb / conventional milling direction or entry strategy unsuitable", "Review toolpath direction, entry and exit strategy."),
    ]),
    "VMC_MILL": ("VMC milling process checks", [
        ("Wrong work offset / fixture offset selected", "Verify G54-G59 or extended work offset against setup sheet."),
        ("Tool length / radius compensation or tool pocket mapping incorrect", "Audit H / D offsets, tool pocket and sister-tool mapping."),
        ("ATC seating, spindle taper cleanliness or pull-stud condition", "Inspect taper contact, pull stud and tool seating repeatability."),
        ("Rotary axis / 4th-axis zero or clamp condition incorrect", "Verify rotary zero, axis calibration and clamp confirmation where applicable."),
    ]),
    "CNC_MILL": ("CNC milling process checks", [
        ("Wrong work offset / fixture offset selected", "Verify active work offset against setup sheet."),
        ("Tool length / radius compensation or tool mapping incorrect", "Audit H / D offsets and tool number mapping."),
        ("Spindle taper or tool retention condition defective", "Inspect taper, pull stud and tool seating."),
        ("Program coordinate or cutter compensation entry incorrect", "Review program coordinates and compensation activation."),
    ]),
    "DRILL": ("Drilling process checks", [
        ("Drill point angle, lip height or web condition unequal", "Inspect drill geometry and compare both cutting lips."),
        ("Drill wander due to poor spot / pilot drilling", "Check spot drill size, pilot alignment and entry surface."),
        ("Peck depth / retract strategy causes chip packing", "Review peck cycle, retract clearance and chip evacuation."),
        ("Drill breakthrough support or backing condition inadequate", "Inspect exit support and breakthrough strategy."),
    ]),
    "BORE": ("Boring process checks", [
        ("Boring bar overhang or bar damping inadequate", "Measure overhang and verify damping / stiffness arrangement."),
        ("Boring head adjustment or insert setting incorrect", "Verify micrometer setting, insert seating and tool calibration."),
        ("Bore entry / exit strategy causes deflection", "Review approach, dwell, entry and exit toolpath."),
        ("Fine boring allowance or spring pass strategy unsuitable", "Compare finishing allowance and spring-pass plan with validated process."),
    ]),
    "REAM": ("Reaming process checks", [
        ("Pre-drilled hole size or straightness unsuitable", "Measure pre-hole size, straightness and allowance before reaming."),
        ("Reamer runout or alignment with pre-hole incorrect", "Measure tool runout and verify spindle / guide alignment."),
        ("Reaming speed, feed or stock allowance incorrect", "Compare actual parameters and reaming allowance with tool recommendation."),
        ("Reamer margin damage or chip packing", "Inspect margins, flutes and chip evacuation."),
    ]),
    "GRIND": ("Grinding process checks", [
        ("Wheel specification / balance unsuitable for operation", "Verify wheel grade, structure, balance and speed rating."),
        ("Wheel dressing profile or frequency incorrect", "Inspect dressed profile and compare dressing interval with standard."),
        ("Grinding infeed, traverse or spark-out incorrect", "Compare cycle parameters with validated grinding process."),
        ("Coolant nozzle placement or filtration inadequate", "Check nozzle alignment, flow, filtration and coolant condition."),
    ]),
    "TAP": ("Tapping process checks", [
        ("Tap drill size / chamfer not suitable for thread", "Measure pre-hole and chamfer against thread preparation standard."),
        ("Rigid tapping synchronisation or floating holder incorrect", "Verify spindle-feed synchronisation and holder compensation."),
        ("Tap type / flute direction unsuitable for blind or through hole", "Check tap geometry and chip evacuation direction for hole type."),
        ("Tap depth / reversal timing incorrect", "Verify programmed depth, bottom clearance and reversal behaviour."),
    ]),
    "THREAD": ("Threading process checks", [
        ("Threading tool profile / insert pitch incorrect", "Verify insert profile and pitch against drawing."),
        ("Threading infeed strategy or pass depth unsuitable", "Review pass sequence, infeed angle and final spring passes."),
        ("Spindle synchronisation or lead control unstable", "Check encoder feedback and synchronised feed / spindle data."),
        ("Thread relief, runout or tool exit clearance inadequate", "Compare relief groove and tool exit with drawing requirements."),
    ]),
    "FACE": ("Facing process checks", [
        ("Face tool centre height or insert seating incorrect", "Check centre height, insert seating and cutter face runout."),
        ("Facing pass overlap or toolpath leaves step", "Review path overlap, start / end points and finishing pass."),
        ("Workpiece axial seating or stop reference inconsistent", "Verify axial stop contact and part seating."),
        ("Facing tool deflection under interrupted cut", "Inspect tool rigidity and cutting load during the face pass."),
    ]),
    "SLOT": ("Slotting process checks", [
        ("Slot cutter width, runout or side clearance incorrect", "Measure cutter width, runout and side clearance."),
        ("Slot depth / width strategy causes cutter deflection", "Review depth per pass, engagement and tool stiffness."),
        ("Chip packing in slot causes recutting or tool overload", "Inspect chip evacuation and coolant / air delivery."),
        ("Slot end radius / corner path differs from drawing", "Compare tool diameter and programmed end geometry with drawing."),
    ]),
    "HONE": ("Honing process checks", [
        ("Honing stone grade, grit or bond unsuitable", "Verify stone specification against material and required surface."),
        ("Stone expansion pressure or contact pattern incorrect", "Check expansion setting and contact pattern over the bore."),
        ("Honing stroke, rotation ratio or dwell incorrect", "Review stroke length, rotation ratio and cycle time."),
        ("Honing fluid filtration / flow inadequate", "Check fluid condition, filtration and flow at honing zone."),
    ]),
    "BROACH": ("Broaching process checks", [
        ("Broach tooth wear, chipping or pitch damage", "Inspect tooth condition and compare wear with broach life criteria."),
        ("Broach alignment or guide bush condition incorrect", "Check alignment, guide bush wear and entry guidance."),
        ("Broach pull / push force or stroke speed outside range", "Review force trend, stroke speed and machine limits."),
        ("Chip clearance or lubrication inadequate", "Inspect chip pockets and lubricant delivery along the broach."),
    ]),
    "OTHER": ("Operation-specific checks", [
        ("Special process tooling / fixture specification not followed", "Identify the approved special-process setup and compare actual condition."),
        ("Process sequence or parameter window not validated", "Review process validation and actual parameter record."),
        ("Machine-specific alignment or calibration outside limits", "Check the relevant machine acceptance and calibration records."),
        ("Inspection method not matched to the operation", "Verify control plan measurement method and acceptance criteria."),
    ]),
}

def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

def _branch(node_id, label, children):
    return {
        "id": node_id, "label": label, "type": "INTERMEDIATE_EVENT",
        "gate": "OR", "children": children,
    }

def _leaf(node_id, label, requirement):
    return {
        "id": node_id, "label": label, "type": "BASIC_EVENT",
        "gate": None, "children": [], "requirement": requirement,
    }

def _expanded_tree(operation_code, defect_code, defect_name, operation_name):
    children = []
    for group_index, (group_name, causes) in enumerate(CORE_GROUPS, 1):
        leaves = [
            _leaf(f"core_{group_index}_{i}", label, requirement)
            for i, (label, requirement) in enumerate(causes, 1)
        ]
        children.append(_branch(f"core_group_{group_index}", group_name, leaves))

    defect_group, defect_causes = DEFECT_CAUSES[defect_code]
    children.append(_branch(
        "defect_specific",
        defect_group,
        [_leaf(f"defect_{i}", label, requirement)
         for i, (label, requirement) in enumerate(defect_causes, 1)],
    ))

    operation_group, operation_causes = OPERATION_CAUSES.get(
        operation_code, OPERATION_CAUSES["OTHER"]
    )
    children.append(_branch(
        "operation_specific",
        operation_group,
        [_leaf(f"operation_{i}", label, requirement)
         for i, (label, requirement) in enumerate(operation_causes, 1)],
    ))

    return {
        "id": "top_event",
        "label": f"{defect_name} – non-conforming component",
        "type": "TOP_EVENT",
        "gate": "OR",
        "children": children,
        "notes": (
            f"Expanded V2 investigation prompts for {operation_name} and {defect_name}. "
            "These are possible causes, not verified conclusions. Investigators must "
            "confirm or rule out each relevant cause using objective evidence. "
            "Requirement / specification fields are guidance only and may be adapted "
            "to the drawing, control plan and approved process."
        ),
    }


def upgrade():
    bind = op.get_bind()
    operations = bind.execute(sa.text(
        "SELECT code, name FROM fta_operations WHERE is_active = true"
    )).mappings().all()
    defects = bind.execute(sa.text(
        "SELECT code, name FROM fta_defect_library WHERE is_active = true"
    )).mappings().all()

    operation_names = {row["code"]: row["name"] for row in operations}
    defect_names = {row["code"]: row["name"] for row in defects}

    # Original seed codes retain their original operation prefix. CNC_MILL was
    # later renamed to VMC_MILL in the operation master, but its template code
    # remains CNC_MILL-<DEFECT_CODE>.
    operation_prefixes = {
        "VMC_MILL": ("CNC_MILL", "VMC_MILL"),
    }
    inserted = 0
    skipped = 0

    for operation_code, operation_name in operation_names.items():
        if operation_code not in OPERATION_CAUSES:
            operation_code_for_causes = "OTHER"
        else:
            operation_code_for_causes = operation_code

        for defect_code, defect_name in defect_names.items():
            prefixes = operation_prefixes.get(operation_code, (operation_code,))
            source = None
            for prefix in prefixes:
                source = bind.execute(sa.text("""
                    SELECT * FROM fta_templates
                    WHERE code=:code AND operation_code=:operation_code
                      AND defect_code=:defect_code
                    ORDER BY version DESC LIMIT 1
                """), {
                    "code": f"{prefix}-{defect_code}",
                    "operation_code": operation_code,
                    "defect_code": defect_code,
                }).mappings().first()
                if source:
                    break
            if not source:
                skipped += 1
                continue

            # Do not overwrite or supersede templates that already have a
            # user-created revision. Only untouched original V1 seed templates
            # receive the generated V2.
            max_version = bind.execute(sa.text(
                "SELECT MAX(version) FROM fta_templates WHERE code=:code"
            ), {"code": source["code"]}).scalar_one()
            if max_version != 1:
                skipped += 1
                continue

            tree = _expanded_tree(
                operation_code_for_causes, defect_code, defect_name, operation_name
            )
            bind.execute(sa.text("""
                INSERT INTO fta_templates
                    (code, name, operation_code, defect_code, version, status,
                     tree_json, created_by_id, updated_by_id, created_at, updated_at)
                VALUES
                    (:code, :name, :operation_code, :defect_code, 2, 'PUBLISHED',
                     :tree_json, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """), {
                "code": source["code"],
                "name": source["name"],
                "operation_code": operation_code,
                "defect_code": defect_code,
                "tree_json": json.dumps(tree, ensure_ascii=False),
            })
            inserted += 1

    # Fail safely if no default template was upgraded: this usually means the
    # migration is being applied to an unexpected database state.
    if inserted == 0:
        raise RuntimeError(
            "No default FTA templates were expanded. Verify the existing "
            "operation, defect and seeded template codes before retrying."
        )


def downgrade():
    # V2 rows may already be referenced by investigations. Never delete them
    # automatically; use a reviewed forward migration if a rollback is needed.
    raise RuntimeError(
        "Expanded FTA V2 templates are preserved to protect investigation "
        "references. Restore a verified backup or use a reviewed forward migration."
    )
