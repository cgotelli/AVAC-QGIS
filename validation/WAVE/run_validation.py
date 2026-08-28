#!/usr/bin/env python3
"""Run the six Delestre/SWASHES benchmarks with AVAC or WAVE source."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
RUN_ROOT = HERE
SOLVER_KIND = "avac"

from avac4qgis_validation.runtime import (
    GRAVITY,
    fgout_frame,
    fgout_times,
    prepare_avac_hydraulic_case,
    prepare_wave_hydraulic_case,
    run_solver,
    runtime,
    solver_executable,
)
from swashes_reference import save_reference, solution  # noqa: E402


CASES = {
    "transcritical_shock": "01_transcritical_shock",
    "macdonald_smooth_shock": "02_macdonald_smooth_shock",
    "ritter_dry_dam_break": "03_ritter_dry_dam_break",
    "thacker_planar_paraboloid": "04_thacker_planar_paraboloid",
    "pseudo2d_supercritical": "05_macdonald_pseudo2d_supercritical",
    "pseudo2d_subcritical": "06_macdonald_pseudo2d_subcritical",
}


def model_label() -> str:
    return "AVAC" if SOLVER_KIND == "avac" else "WAVE"


def comparison_stem() -> str:
    return f"{SOLVER_KIND}_vs_swashes"


def prepare_hydraulic_case(*args, **kwargs):
    prepare = (
        prepare_avac_hydraulic_case
        if SOLVER_KIND == "avac"
        else prepare_wave_hydraulic_case
    )
    return prepare(*args, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def final_frame(work: Path):
    times = fgout_times(SOLVER_KIND, work)
    if not times:
        raise RuntimeError(f"{model_label()} wrote no fixed-grid output.")
    with contextlib.redirect_stdout(io.StringIO()):
        return fgout_frame(SOLVER_KIND, work, len(times))


def centerline(frame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    middle = frame.h.shape[1] // 2
    return (
        np.asarray(frame.X[:, middle], dtype=float),
        np.asarray(frame.h[:, middle], dtype=float),
        np.asarray(frame.B[:, middle], dtype=float),
        np.asarray(frame.hu[:, middle], dtype=float),
    )


def nearest_reference(reference: np.ndarray, x: np.ndarray, column: int) -> np.ndarray:
    return np.interp(x, reference[:, 0], reference[:, column])


def base_summary(case_name: str, work: Path, dx: float, frame) -> dict[str, object]:
    return {
        "case": case_name,
        "solver": str(solver_executable(SOLVER_KIND)),
        "solver_sha256": sha256(solver_executable(SOLVER_KIND)),
        "dx_m": dx,
        "final_time_s": float(frame.t),
        "water_model": f"{model_label()} Water",
    }


def store(case_dir: Path, summary: dict[str, object], columns: np.ndarray,
          header: str) -> None:
    results = case_dir / "results"
    results.mkdir(exist_ok=True)
    np.savetxt(results / f"{comparison_stem()}.csv", columns, delimiter=",",
               header=header, comments="")
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def plot_steady_1d(case_dir: Path, x: np.ndarray, h: np.ndarray, bed: np.ndarray,
                   reference: np.ndarray, title: str, *, plot_surface: bool) -> None:
    figures = case_dir / "figures"
    figures.mkdir(exist_ok=True)
    ref_h = nearest_reference(reference, x, 1)
    ref_b = nearest_reference(reference, x, 3)
    ref_critical = nearest_reference(reference, x, 7)
    fig, axis = plt.subplots(figsize=(8.2, 4.8))
    if plot_surface:
        axis.plot(x, bed+h, color="#0057b8", ls=(0, (1.5, 1.5)), lw=2.0,
                  label=model_label())
        axis.plot(x, ref_b+ref_h, color="#d62728", lw=1.5,
                  label="Analytical solution")
        ylabel = "water-surface elevation (m)"
    else:
        axis.plot(x, h, color="#0057b8", ls=(0, (1.5, 1.5)), lw=2.0,
                  label=model_label())
        axis.plot(x, ref_h, color="#d62728", lw=1.5,
                  label="Analytical solution")
        ylabel = "water depth (m)"
    axis.plot(x, ref_critical, color="black", ls="--", lw=1.0,
              label="Critical surface")
    axis.plot(x, ref_b, color="#ff6f3c", ls=(0, (1, 1)), lw=1.1,
              label="Topography")
    axis.set(xlabel="x (m)", ylabel=ylabel, title=title)
    axis.grid(alpha=0.22)
    axis.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(figures / f"{comparison_stem()}.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def run_transcritical(case_dir: Path, cores: int) -> dict[str, object]:
    dx = 25.0/500.0
    reference, text = solution(1, 1, 1, 3, 2500)
    save_reference(case_dir/"reference", reference, text,
                   "x_m,h_m,u_m_s,bed_m,q_m2_s,eta_m,froude,critical_eta_m")
    bed_fn = lambda X, Y: np.maximum(0.0, 0.2-0.05*(X-10.0)**2)
    work = prepare_hydraulic_case(
        case_dir, xlower=0.0, xupper=25.0, ylower=0.0, yupper=5*dx,
        dx=dx, t_final=100.0, nout=20, bed=bed_fn,
        depth=lambda X, Y: np.maximum(0.33-bed_fn(X,Y), 0.0),
        boundary_west="user", boundary_east="user",
        boundary_south="periodic", boundary_north="periodic",
        hydraulic_boundaries={1: (2, 0.0, 0.18), 2: (1, 0.33, 0.0)},
        max1d=130,
    )
    run_solver(SOLVER_KIND, work, cores=cores)
    frame = final_frame(work)
    x,h,b,hu = centerline(frame)
    ref_h = nearest_reference(reference,x,1)
    summary = base_summary("Transcritical flow with shock",work,dx,frame)
    summary.update({"cells_x":500,"cells_y":5,"rmse_depth_m":float(np.sqrt(np.mean((h-ref_h)**2))),
                    "maximum_absolute_depth_error_m":float(np.max(np.abs(h-ref_h)))})
    store(case_dir,summary,np.column_stack((x,h,b,h+b,ref_h,nearest_reference(reference,x,3))),
          "x_m,model_h_m,model_bed_m,model_eta_m,swashes_h_m,swashes_bed_m")
    plot_steady_1d(case_dir,x,h,b,reference,"Transcritical flow with shock — steady state",
                   plot_surface=False)
    return summary


def run_macdonald_1d(case_dir: Path, cores: int) -> dict[str, object]:
    dx = 100.0/500.0
    reference, text = solution(1, 2, 2, 2, 2500)
    save_reference(case_dir/"reference",reference,text,
                   "x_m,h_m,u_m_s,bed_m,q_m2_s,eta_m,froude,critical_eta_m")
    z = lambda X: np.interp(X,reference[:,0],reference[:,3])
    z_out = float(reference[-1,3]); h_out = float(reference[-1,1])
    bed_fn = lambda X,Y: z(X)
    work = prepare_hydraulic_case(
        case_dir,xlower=0.0,xupper=100.0,ylower=0.0,yupper=5*dx,
        dx=dx,t_final=1500.0,nout=30,bed=bed_fn,
        depth=lambda X,Y: np.maximum(h_out+z_out-z(X),0.0),manning=0.0328,
        boundary_west="user",boundary_east="user",
        boundary_south="periodic",boundary_north="periodic",
        hydraulic_boundaries={1:(2,0.0,2.0),2:(1,h_out+z_out,0.0)},max1d=130,
    )
    run_solver(SOLVER_KIND,work,cores=cores)
    frame=final_frame(work); x,h,b,hu=centerline(frame)
    ref_h=nearest_reference(reference,x,1)
    summary=base_summary("MacDonald smooth transition and shock",work,dx,frame)
    summary.update({"cells_x":500,"cells_y":5,"manning_n":0.0328,
                    "rmse_depth_m":float(np.sqrt(np.mean((h-ref_h)**2))),
                    "maximum_absolute_depth_error_m":float(np.max(np.abs(h-ref_h)))})
    store(case_dir,summary,np.column_stack((x,h,b,h+b,ref_h,nearest_reference(reference,x,3))),
          "x_m,model_h_m,model_bed_m,model_eta_m,swashes_h_m,swashes_bed_m")
    plot_steady_1d(case_dir,x,h,b,reference,"MacDonald smooth transition and shock — t = 1500 s",
                   plot_surface=True)
    return summary


def run_ritter(case_dir: Path, cores: int) -> dict[str, object]:
    dx=10.0/500.0
    reference,text=solution(1,3,1,2,2500)
    save_reference(case_dir/"reference",reference,text,
                   "x_m,h_m,u_m_s,bed_m,q_m2_s,eta_m,froude,critical_eta_m")
    work=prepare_hydraulic_case(
        case_dir,xlower=0.0,xupper=10.0,ylower=0.0,yupper=5*dx,dx=dx,
        t_final=6.0,nout=60,bed=lambda X,Y:np.zeros_like(X),
        depth=lambda X,Y:np.where(X<=5.0,0.005,0.0),
        boundary_west="wall",boundary_east="extrap",
        boundary_south="periodic",boundary_north="periodic",max1d=130,
    )
    run_solver(SOLVER_KIND,work,cores=cores)
    frame=final_frame(work); x,h,b,hu=centerline(frame)
    ref_h=nearest_reference(reference,x,1)
    summary=base_summary("Ritter dry-domain dam break",work,dx,frame)
    summary.update({"cells_x":500,"cells_y":5,"rmse_depth_m":float(np.sqrt(np.mean((h-ref_h)**2))),
                    "maximum_absolute_depth_error_m":float(np.max(np.abs(h-ref_h)))})
    store(case_dir,summary,np.column_stack((x,h,ref_h)),"x_m,model_h_m,swashes_h_m")
    figures=case_dir/"figures"; figures.mkdir(exist_ok=True)
    fig,axis=plt.subplots(figsize=(8.2,4.6))
    axis.plot(x,h,color="#0057b8",ls=(0,(1.5,1.5)),lw=2,label=model_label())
    axis.plot(x,ref_h,color="#d62728",lw=1.5,label="Analytical solution")
    axis.set(xlabel="x (m)",ylabel="water depth (m)",title="Dry-domain dam break — t = 6 s")
    axis.grid(alpha=.22); axis.legend(frameon=False); fig.tight_layout()
    fig.savefig(figures/f"{comparison_stem()}.png",dpi=240,bbox_inches="tight"); plt.close(fig)
    return summary


def thacker_fields(X: np.ndarray,Y: np.ndarray,t: float) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
    h0=0.1; a=1.0; eta0=0.5; omega=np.sqrt(2*GRAVITY*h0)/a
    bed=h0*(((X-2.0)**2+(Y-2.0)**2)/a**2-1.0)
    h=eta0*h0/a**2*(2*(X-2.0)*np.cos(omega*t)+2*(Y-2.0)*np.sin(omega*t)-eta0)-bed
    h=np.maximum(h,0.0)
    u=-eta0*omega*np.sin(omega*t); v=eta0*omega*np.cos(omega*t)
    return bed,h,h*u,h*v


def run_thacker(case_dir: Path, cores: int) -> dict[str, object]:
    cells=100
    dx=4.0/cells; omega=np.sqrt(2*GRAVITY*0.1); tfinal=3*2*np.pi/omega
    reference,text=solution(2,1,1,2,500,500)
    save_reference(case_dir/"reference",reference,text,
                   "x_m,y_m,h_m,u_m_s,v_m_s,eta_m,bed_m,speed_m_s,froude,qx_m2_s,qy_m2_s,q_m2_s")
    bed_fn=lambda X,Y:thacker_fields(X,Y,0.0)[0]
    state=lambda X,Y:thacker_fields(X,Y,0.0)[1:]
    work=prepare_hydraulic_case(
        case_dir,xlower=0.0,xupper=4.0,ylower=0.0,yupper=4.0,dx=dx,
        t_final=tfinal,nout=60,bed=bed_fn,state=state,
        boundary_west="wall",boundary_east="wall",boundary_south="wall",boundary_north="wall",
        max1d=cells+4,
    )
    run_solver(SOLVER_KIND,work,cores=cores)
    frame=final_frame(work); x,h,b,hu=centerline(frame)
    _,href,_,_=thacker_fields(x,np.full_like(x,2.0),tfinal)
    summary=base_summary("Thacker planar surface in a paraboloid",work,dx,frame)
    summary.update({"cells_x":cells,"cells_y":cells,"periods":3,
                    "rmse_centerline_depth_m":float(np.sqrt(np.mean((h-href)**2))),
                    "maximum_centerline_depth_error_m":float(np.max(np.abs(h-href)))})
    store(case_dir,summary,np.column_stack((x,h,b,h+b,href)),
          "x_m,model_h_m,model_bed_m,model_eta_m,swashes_h_m")
    figures=case_dir/"figures"; figures.mkdir(exist_ok=True)
    fig,axis=plt.subplots(figsize=(8.2,4.6))
    wet=h>1e-10; refwet=href>0
    axis.plot(x[wet],(b+h)[wet],color="#0057b8",ls=(0,(1.5,1.5)),lw=2,label=model_label())
    axis.plot(x[refwet],(bed_fn(x,np.full_like(x,2.0))+href)[refwet],color="#d62728",lw=1.5,label="Analytical solution")
    axis.plot(x,b,color="#ff6f3c",ls=(0,(1,1)),lw=1.1,label="Topography")
    axis.set(xlabel="x (m)",ylabel="elevation (m)",title="Thacker planar surface — t = 3T")
    axis.grid(alpha=.22); axis.legend(frameon=False); fig.tight_layout()
    fig.savefig(figures/f"{comparison_stem()}.png",dpi=240,bbox_inches="tight"); plt.close(fig)
    return summary


def pseudo_geometry(reference: np.ndarray, kind: str):
    z=lambda X:np.interp(X,reference[:,0],reference[:,2])
    if kind=="supercritical":
        width=lambda X:10.0-5.0*np.exp(-10.0*(X/200.0-0.5)**2)
        def bed(X,Y):
            floor=z(X); inside=np.abs(Y)<=width(X)/2
            return np.where(inside,floor,floor+20.0)
    else:
        width=lambda X:10.0-5.0*np.exp(-50.0*(X/400.0-1/3)**2)-5.0*np.exp(-50.0*(X/400.0-2/3)**2)
        def bed(X,Y):
            floor=z(X)
            return floor+np.maximum(0.0,(np.abs(Y)-width(X)/2)/2.0)
    return z,width,bed


def pseudo2d_mean_depth(frame, width) -> tuple[np.ndarray, np.ndarray]:
    """Return the section-mean free surface expressed as centerline depth.

    Directly averaging depth is incorrect for the B2 trapezoid because depth
    decreases up its side slopes.  Delestre's pseudo-2D ``h`` corresponds to
    the transversely averaged free surface above the centerline bed.
    """
    X=np.asarray(frame.X); H=np.asarray(frame.h); B=np.asarray(frame.B)
    middle=H.shape[1]//2
    x=X[:,middle]
    eta=np.where(H>1.e-10,H+B,np.nan)
    mean_eta=np.nanmean(eta,axis=1)
    return x, mean_eta-B[:,middle]


def plot_pseudo(case_dir: Path, frame, reference: np.ndarray, width,
                title: str) -> None:
    figures=case_dir/"figures"; figures.mkdir(exist_ok=True)
    X=np.asarray(frame.X); Y=np.asarray(frame.Y); H=np.asarray(frame.h)
    x,h,b,hu=centerline(frame)
    x_mean,h_mean=pseudo2d_mean_depth(frame,width)
    ref_h=nearest_reference(reference,x,1); ref_b=nearest_reference(reference,x,2)
    fig,axes=plt.subplots(1,2,figsize=(12.2,4.4))
    mesh=axes[0].pcolormesh(X,Y-Y.min(),H,shading="nearest",cmap="Blues")
    fig.colorbar(mesh,ax=axes[0],label="water depth (m)")
    axes[0].set(xlabel="x (m)",ylabel="y (m)",title=f"{model_label()} water depth")
    axes[1].plot(x_mean,b+h_mean,color="#0057b8",ls=(0,(1.5,1.5)),lw=2,
                 label=f"{model_label()} cross-section mean")
    axes[1].plot(x,ref_b+ref_h,color="#d62728",lw=1.5,label="Analytical solution")
    axes[1].plot(x,ref_b,color="#ff6f3c",ls=(0,(1,1)),lw=1.1,label="Topography")
    axes[1].set(xlabel="x (m)",ylabel="elevation (m)",title="Longitudinal profile")
    axes[1].grid(alpha=.22); axes[1].legend(frameon=False,fontsize=8,loc="lower left")
    fig.suptitle(title); fig.tight_layout()
    fig.savefig(figures/f"{comparison_stem()}.png",dpi=240,bbox_inches="tight"); plt.close(fig)


def run_pseudo(case_dir: Path, cores: int, kind: str,
               dx_override: float | None = None) -> dict[str, object]:
    if kind=="supercritical":
        length=200.0; choice_domain=1; choice=2; tfinal=200.0
    else:
        length=400.0; choice_domain=2; choice=1; tfinal=600.0
    # Both solver packages currently use square raster cells whereas the published FullSWOF
    # grids use much finer transverse than longitudinal spacing.  The abrupt
    # vertical B1 wall therefore needs a finer square grid than the sloping B2
    # section to avoid staircase-generated disturbances.
    dx=(0.2 if kind=="supercritical" else 0.25) if dx_override is None else float(dx_override)
    if dx <= 0 or abs(round(length/dx)*dx-length) > 1.e-9 or abs(round(10.0/dx)*dx-10.0) > 1.e-9:
        raise ValueError("Pseudo-2D dx must divide both the channel length and 10 m transverse domain.")
    reference,text=solution(1.5,1,choice_domain,choice,2500)
    save_reference(case_dir/"reference",reference,text,"x_m,h_m,bed_m,eta_m")
    z,width,bed=pseudo_geometry(reference,kind)
    if kind=="supercritical":
        h_in=float(reference[0,1]); stage_in=float(reference[0,2]+h_in)
        depth=lambda X,Y:np.zeros_like(X)
        west=(5,stage_in,20.0); east="extrap"; boundaries={1:west}
    else:
        h_in=float(reference[0,1]); stage_in=float(reference[0,2]+h_in)
        h_out=float(reference[-1,1]); stage_out=float(reference[-1,2]+h_out)
        depth=lambda X,Y:np.maximum(stage_out-bed(X,Y),0.0)
        east="user"; boundaries={1:(4,stage_in,20.0),2:(1,stage_out,0.0)}
    work=prepare_hydraulic_case(
        case_dir,xlower=0.0,xupper=length,ylower=-5.0,yupper=5.0,dx=dx,
        t_final=tfinal,nout=30,bed=bed,depth=depth,manning=0.03,
        boundary_west="user",boundary_east=east,boundary_south="wall",boundary_north="wall",
        hydraulic_boundaries=boundaries,max1d=int(round(10.0/dx))+4,
    )
    run_solver(SOLVER_KIND,work,cores=cores)
    frame=final_frame(work); x,h,b,hu=centerline(frame)
    x_mean,h_mean=pseudo2d_mean_depth(frame,width)
    ref_h=nearest_reference(reference,x_mean,1)
    label="MacDonald pseudo-2D supercritical" if kind=="supercritical" else "MacDonald pseudo-2D subcritical"
    summary=base_summary(label,work,dx,frame)
    summary.update({"cells_x":int(round(length/dx)),"cells_y":int(round(10/dx)),
                    "manning_n":0.03,
                    "rmse_cross_section_mean_depth_m":float(np.sqrt(np.mean((h_mean-ref_h)**2))),
                    "maximum_cross_section_mean_depth_error_m":float(np.max(np.abs(h_mean-ref_h)))})
    store(case_dir,summary,np.column_stack((x_mean,h_mean,b,b+h_mean,ref_h,
                                           nearest_reference(reference,x_mean,2))),
          "x_m,model_mean_h_m,model_center_bed_m,model_mean_eta_m,swashes_h_m,swashes_bed_m")
    plot_pseudo(case_dir,frame,reference,width,label+" — steady state")
    return summary


def run_case(name: str, cores: int = 8,
             pseudo_dx: float | None = None) -> dict[str, object]:
    case_dir=RUN_ROOT/CASES[name]
    case_dir.mkdir(parents=True,exist_ok=True)
    if name=="transcritical_shock": return run_transcritical(case_dir,cores)
    if name=="macdonald_smooth_shock": return run_macdonald_1d(case_dir,cores)
    if name=="ritter_dry_dam_break": return run_ritter(case_dir,cores)
    if name=="thacker_planar_paraboloid": return run_thacker(case_dir,cores)
    if name=="pseudo2d_supercritical": return run_pseudo(case_dir,cores,"supercritical",pseudo_dx)
    if name=="pseudo2d_subcritical": return run_pseudo(case_dir,cores,"subcritical",pseudo_dx)
    raise KeyError(name)


def main() -> None:
    global RUN_ROOT,SOLVER_KIND
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case",choices=["all",*CASES])
    parser.add_argument("--cores",type=int,default=8)
    parser.add_argument("--pseudo-dx",type=float,default=None,
                        help="Override square cell size for either pseudo-2D case")
    parser.add_argument("--solver",choices=("avac","wave"),default="avac")
    parser.add_argument("--output-root",type=Path,default=HERE,
                        help="Root containing the numbered case directories")
    args=parser.parse_args()
    SOLVER_KIND=args.solver
    RUN_ROOT=args.output_root.resolve()
    RUN_ROOT.mkdir(parents=True,exist_ok=True)
    names=list(CASES) if args.case=="all" else [args.case]
    summaries={name:run_case(name,args.cores,args.pseudo_dx) for name in names}
    (RUN_ROOT/"comparison_summary.json").write_text(json.dumps(summaries,indent=2)+"\n")
    print(json.dumps(summaries,indent=2))


if __name__=="__main__":
    main()
