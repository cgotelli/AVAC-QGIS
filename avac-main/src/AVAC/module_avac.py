# AVAC module version 1.4
import os
from os.path import expanduser
import numpy as np
import tarfile, re, subprocess, sys, yaml, shutil
from linecache import getline
from clawpack.geoclaw import topotools as topo
import geopandas as gp
from pathlib import Path

# Last update: 4 May 2026
# C. Ancey

#####################
# various functions #
#####################
def find_nearest(array, value):
    array = np.asarray(array)
    idx = (np.abs(array - value)).argmin()
    return idx

# Function to flatten a nested dictionary
def flatten_dict(d, parent_key='', sep='.'):
    """
    flattens the original (nested) dictionary of variables
    """
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items

def format_numbers(features):
    """ 
    Format numbers to two decimal places if they are floats
    """
    formatted_features = []
    for feature in features:
        name, value = feature
        if isinstance(value, float):  # Check if the value is a float
            formatted_value = f"{value:>10.2f}"  # Format to two decimal places and right-align
        else:
            formatted_value = f"{value:>10}"  # Right-align non-float values
        formatted_features.append([name, formatted_value])
    return formatted_features

############
# clawpack #
############

# check if clawpack is installed
def check_claw():
    """ 
    Test if clawpack is installed. If so, it returns the CLAW path
    """
    CLAW = os.environ['CLAW']
    home = expanduser("~")
    if CLAW=='':
        claw = False
        with open(home+'/.bashrc') as f:
            datafile = f.readlines()
        for line in datafile:
            s="CLAW"
            if s in line and line.find('#')==-1:
                claw=(str.split(line))[1]
                claw = home+claw.replace("CLAW=$HOME", "")
                return claw
        if not claw:
            print("Error: I cannot determine the $CLAW variable...")
            print("Please modify the script and define it explicitely")
            return claw
    else:
        return CLAW
    
def check_version(claw):
    claw_setup = claw+"/setup.py"
    # Open the file
    with open(claw_setup, "r") as file:
        # Initialize variables to store MAJOR and MINOR values
        major_value = None
        minor_value = None
        # Iterate through each line in the file
        for line in file:
            # Strip leading/trailing whitespace
            line = line.strip()
            # Check if the line starts with "MAJOR" and contains "="
            if line.startswith("MAJOR") and "=" in line:
                # Split the line by "=" and extract the value
                parts = line.split("=")
                if len(parts) == 2:                      # Ensure the line is properly formatted
                    major_value = int(parts[1].strip())  # Extract and convert to integer
            # Check if the line starts with "MINOR" and contains "="
            elif line.startswith("MINOR") and "=" in line:
                parts = line.split("=")
                if len(parts) == 2:   
                    minor_value = int(parts[1].strip())  #  
    return [major_value,minor_value]


def get_version_from_file(file_path):
    """Extract the version from a file if it exists in the working directory."""
    # Regular expression to extract filename & version number
    pattern = r"[#!]\s*([\w\.]+).*?version\s*=\s*([\d\.]+)"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            match = re.search(pattern, first_line)
            if match:
                return match.group(1), float(match.group(2))  # Return (filename, version)
    except Exception:
        pass  # Ignore errors
    return None, None


def install_avac(**kwargs):
    """ 
    This function extracts the files required by AVAC
    options:
    - verbosity = False by default, makes the execution verbose or not
    - path = '.' by default (working directory). If a new path is specified
      and does not exist, it is created
    - archive = 'files.tar.gz' by default
    """
    path = kwargs.get('path', '.')
     
    if not isinstance(path,str): 
        print(f"Error. Check your path definition! You set path = {path}.")
    else:
        if os.path.isdir(path):
            print(f"Installation of AVAC in the working directory: {os.getcwd()}")
        else:
            print(f"Installation of AVAC in the new directory {os.getcwd()+'/'+path}")
            os.makedirs(path)
    
    archive = kwargs.get('archive', 'files.tar.gz')
    verbosity = kwargs.get('verbosity', False)
      
    #extract_path = '.'  # Extract to current directory
    if not os.path.isfile(archive): 
        print(f"Installation impossible. Archive {archive} is missing.")
        print(f"Stopped...")
    else:
        # Regular expression to extract filename & version number
        pattern = r"[#!]\s*([\w\.]+).*?version\s*=\s*([\d\.]+)"

        # Open the tar.gz archive
        with tarfile.open(archive, "r:gz") as tar:
            file_names = tar.getnames()

            for target_file in file_names:
                extracted_file = tar.extractfile(target_file)

                if extracted_file:  # Ignore directories                    
                    # Read first line separately to extract version
                    first_line = extracted_file.readline().decode().strip()
                    match = re.search(pattern, first_line)

                    if match:
                        filename = match.group(1)  # Extract filename
                        archive_version = float(match.group(2))  # Extract version
                        file_path = os.path.join(path, filename)

                        # Read the remaining content after the first line
                        remaining_content = extracted_file.read()

                        # Check if file exists in the working directory
                        if os.path.exists(file_path):
                            _, existing_version = get_version_from_file(file_path)
                            
                            if existing_version is None or existing_version < archive_version:
                                if verbosity:
                                    print(f"Updating {filename} (Old: {existing_version}, New: {archive_version})")
                                with open(file_path, "wb") as f_out:
                                    f_out.write((first_line + "\n").encode())  # Restore first line
                                    f_out.write(remaining_content)  # Write the rest
                            else:
                                if verbosity:
                                    print(f"Skipping {filename}, version {existing_version} is up to date.")
                        else:
                            if verbosity: print(f"Extracting new file: {filename}")
                            with open(file_path, "wb") as f_out:
                                f_out.write((first_line + "\n").encode())  # Restore first line
                                f_out.write(remaining_content)  # Write the rest
    print(f"=> You are using AVAC version {get_version_from_file('Makefile')[1]}.")

# running AVAC


def make_output(avac_p, verbosity=False):
    """
    Executes 'make clean', then 'make .output', with a progress bar.
    Progress is tracked by counting fort.t???? files written to _output,
    which is robust regardless of stdout buffering in xgeoclaw.
    Input:
        * avac_p   : dictionary of configuration parameters
        * verbosity: if True, also print every line to the console;
                    otherwise only the progress bar is shown.
    Output: 
        * output files in _output, avac.log.

    Mass-monitoring parameters (read from avac_p['computation'], all optional):
        * track_mass    : bool  — if True (default), compute wet/moving mass at each
                        frame and write _output/mass.txt. Set to False to skip
                        this step (faster runs, no early-stop possible).
        * mass_frac_stop: float — moving_mass / initial_mass threshold below which
                        early stop is triggered (default 0.05 = 5 %).
                        Only used when track_mass=True.
        * force_stop    : bool  — if True, kill the entire xgeoclaw process group
                        when early stop fires (guarantees the solver actually
                        stops). If False (default), only the 'make' parent process
                        is terminated; xgeoclaw may keep running.
    """
    import glob as _glob
    import time as _time

    if not isinstance(verbosity, bool):
        verbosity = False
    t_0      = avac_p['computation'].get('t_0',0)
    tmax     = avac_p['computation']['t_max']
    nb_simul = avac_p['computation']['nb_simul']
    outdir   = avac_p['computation']['output_directory']
    dt       = (tmax-t_0) / nb_simul

    track_mass     = bool(avac_p['computation'].get('track_mass',     True))
    mass_frac_stop = float(avac_p['computation'].get('mass_frac_stop', 0.03))
    force_stop     = bool(avac_p['computation'].get('force_stop',     False))

    print(f"AVAC computation: t = {t_0} → {tmax} s  |  {nb_simul} frames  |  dt = {dt:.1f} s")
    if track_mass:
        if avac_p['output']['Language']=='French':
            print(f"  Suivi de la masse : oui  |  seuil d'arrêt : {100*mass_frac_stop:.0f} %  |  "
              f"forcer l'arrêt ? {'Oui' if force_stop else 'Non'}")
        else:
            print(f"  Mass tracking: ON  |  stop threshold: {100*mass_frac_stop:.0f} %  |  "
              f"force stop: {'YES' if force_stop else 'no'}")
    else:
        if avac_p['output']['Language']=='French':
            print("  Suivi de la masse en écoulement : non")
        else:
            print(f"  Mass tracking: off")

    # Clean previous run (force recomputation), then recreate outdir
    # so Fortran can open files in it before runclaw.py gets there.
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    for sentinel in ['.output', '.data']:
        try:
            os.remove(sentinel)
        except FileNotFoundError:
            pass
    subprocess.run(["make", "clean"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    import threading as _threading

    # Launch make in a new session so that, if needed, we can send a signal
    # to the whole process group (make + xgeoclaw children).
    process = subprocess.Popen(
        ["make", ".output"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

    # Thread: write stdout to avac.log in real time
    def _log_writer():
        with open("avac.log", "w") as log_file:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
                if verbosity:
                    sys.stdout.write(line)
                    sys.stdout.flush()

    log_thread = _threading.Thread(target=_log_writer, daemon=True)
    log_thread.start()

    # ------------------------------------------------------------------ #
    # Mass monitoring (optional)                                           #
    # ------------------------------------------------------------------ #
    rho          = avac_p['rheology']['rho']
    dry_tol      = avac_p['computation'].get('dry_limit', 0.001)
    vel_min      = avac_p['computation'].get('mass_threhsold_velocity', 0.01)   # m/s — threshold for "moving" cell
    initial_mass = bool(avac_p['computation'].get('initial_mass', True))

    mass_file     = os.path.join(outdir, "mass.txt")
    mass_initial  = None   # set from first frame with wet > 0
    stopped_early = False

    def _read_frame_mass(frame_idx):
        """Return (total_wet_mass_kg, moving_mass_kg) from fort.q<frame_idx>."""
        try:
            from clawpack import pyclaw as _pyclaw
            sol = _pyclaw.Solution()
            fmt = avac_p['output']['output_format']
            file_format = 'ascii' if fmt == 'ascii' else 'binary'
            sol.read(frame_idx, path=outdir, file_format=file_format,
                     read_aux=False)
            wet_mass = mov_mass = 0.0
            for state in sol.states:
                dx_s, dy_s = state.grid.delta
                h  = state.q[0]
                hu = state.q[1]
                hv = state.q[2]
                wet    = h > dry_tol
                h_safe = np.where(wet, h, 1.0)
                spd    = np.where(wet,
                               np.sqrt((hu/h_safe)**2 + (hv/h_safe)**2),
                               0.0)
                wet_mass += rho * np.sum(h[wet]) * dx_s * dy_s
                mov_mass += rho * np.sum(h[wet & (spd > vel_min)]) * dx_s * dy_s
            return wet_mass, mov_mass
        except Exception:
            return None, None

    def _kill_process():
        """Terminate the solver. With force_stop, kill the whole process group."""
        if force_stop:
            import signal
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass   # process already finished
        else:
            process.terminate()

    if track_mass:
        # Write CSV header for mass.txt (pandas-friendly)
        with open(mass_file, "w") as _mf:
            _mf.write("t_s,wet_mass_kg,moving_mass_kg,fraction\n")

    # ------------------------------------------------------------------ #
    # Main thread: poll fort.t???? files to drive the progress bar        #
    # ------------------------------------------------------------------ #
    last_frame = 0
    t_start = _time.time()

    def _print_bar(frames_done):
        elapsed = _time.time() - t_start
        pct = int(100 * frames_done / nb_simul)
        filled = pct // 5
        bar = "█" * filled + "░" * (20 - filled)
        if frames_done > 0:
            eta = elapsed * (nb_simul - frames_done) / frames_done
            if avac_p['output']['Language']=='French':
                time_str = f"  temps écoulé {elapsed:.0f}s  | fin estimé du calcul dans ~{eta:.0f} s"
            else:
                time_str = f"  elapsed {elapsed:.0f}s  estimated time to completion ~{eta:.0f} s" 
        else:
            if avac_p['output']['Language']=='French':
                time_str = f"  temps écoulé {elapsed:.0f} s"
            else:
                time_str = f"  elapsed {elapsed:.0f} s"
        sys.stdout.write(f"\r  [{bar}] {pct:3d}%  frame {frames_done}/{nb_simul}{time_str}")
        sys.stdout.flush()

    while process.poll() is None:
        frames_done = len(_glob.glob(os.path.join(outdir, "fort.t????")))
        if frames_done > last_frame:
            _print_bar(frames_done)

            if track_mass:
                frame_idx = frames_done - 1
                t_sim = frame_idx * tmax / nb_simul + t_0
                wet, mov = _read_frame_mass(frame_idx)
                if wet is not None:
                    if mass_initial is None and wet > 0:
                        mass_initial = wet
                    frac = mov / mass_initial if mass_initial else float('nan')
                    with open(mass_file, "a") as _mf:
                        _mf.write(f"{t_sim:.3f},{wet:.1f},{mov:.1f},{frac:.4f}\n")
                    # Early-stop check (skip frame 0)
                    if frame_idx > 0 and mass_initial and frac < mass_frac_stop and initial_mass:
                        if avac_p['output']['Language']=='French':
                            sys.stdout.write(
                                f"\nAVA C: arrêt prématuré car la masse vaut {100*frac:.1f}% "
                                f"de la masse initiale à t = {t_sim:.1f} s\n")
                        else:
                            sys.stdout.write(
                            f"\nAVAC: early stop — moving mass = {100*frac:.1f}% "
                            f"of initial at t = {t_sim:.1f} s\n")
                        sys.stdout.flush()
                        _kill_process()
                        stopped_early = True

            last_frame = frames_done
        _time.sleep(0.5)

    log_thread.join()

    # Catch any frames written in the last polling interval
    frames_done = len(_glob.glob(os.path.join(outdir, "fort.t????")))
    if frames_done > last_frame:
        _print_bar(frames_done)

    sys.stdout.write("\n")
    sys.stdout.flush()

    if stopped_early:
        if avac_p['output']['Language']=='French':
            print(f"Arrêt du calcul, car la masse est : {mass_file}")
        else:
            print(f"Computation stopped early. Mass history: {mass_file}")
    elif process.returncode == 0:
        if avac_p['output']['Language']=='French':
            print("Calcul achevé avec succès.")
        else:
            print("Computation successful.")
    else:
        if avac_p['output']['Language']=='French':
            print("Échec du calcul. Voir le fichier 'avac.log'.")
        else:
            print("Failed! See avac.log.")


# animation
def make_animation(avac_p,verbosity=True):
    """
    Progress bar added
    Execute the animation script make_fgout_animation.py
    Input:
    * avac_p : dictionary of configuration parameters
    * Optional argument -> verbosity (Boolean): If True, displays messages during execution; otherwise,
                            directs the messages to the file 'animation.log'.
    Output: mp4 and html files, animation.log.
    """
    import time as _time

    if not isinstance(verbosity, bool):
        verbosity = True
    print(f"I will make an animation for the {avac_p['animation']['variable']} variable.")
    tmax   = avac_p['computation']['t_max']
    n_frames = avac_p['animation']['n_out']
    dt     = tmax / n_frames
    print(f"Times: from t = 0 to t = {tmax} s with a time step dt = {dt} s.")

    frames_done = 0
    in_mp4_phase = False
    t_start = _time.time()

    def _print_bar(n):
        elapsed = _time.time() - t_start
        pct     = int(100 * n / n_frames)
        filled  = pct // 5
        bar     = "█" * filled + "░" * (20 - filled)
        eta_str = (f"  elapsed {elapsed:.0f}s  ETA ~{elapsed*(n_frames-n)/n:.0f}s"
                   if n > 0 else f"  elapsed {elapsed:.0f}s")
        sys.stdout.write(f"\r  [{bar}] {pct:3d}%  frame {n}/{n_frames}{eta_str}")
        sys.stdout.flush()

    def _handle_line(line):
        nonlocal frames_done, in_mp4_phase, t_start
        if not line:
            return
        log_file.write(line)
        if 'Making mp4' in line or 'Making html' in line:
            # début d'une phase de rendu : (ré)initialiser la barre
            in_mp4_phase = True
            frames_done  = 0
            t_start      = _time.time()
            sys.stdout.write(f"  {line.rstrip()}\n")
            sys.stdout.flush()
        elif 'Updating plot' in line and in_mp4_phase:
            frames_done += 1
            _print_bar(frames_done)
        elif 'Created' in line and in_mp4_phase:
            # phase terminée : compléter la barre et passer à la ligne
            _print_bar(n_frames)
            sys.stdout.write("\n")
            sys.stdout.flush()
            in_mp4_phase = False
            if verbosity:
                print(f"  {line.rstrip()}")
        elif verbosity:
            print(line, end="")

    # Appel direct de Python avec -u (stdout non bufferisé) plutôt que via make,
    # ce qui évite la couche intermédiaire et le blocage sur stderr.readline().
    # stderr=STDOUT fusionne les deux flux en un seul pipe (comme make_output).
    import os as _os
    from pathlib import Path as _Path
    _avac_dir = str(_Path(__file__).parent)

    with open("animation.log", "w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-u", "make_fgout_animation.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # fusion stderr → stdout
            text=True,
            bufsize=1,
            cwd=_avac_dir,
        )
        while True:
            line = process.stdout.readline()
            _handle_line(line)
            if not line and process.poll() is not None:
                break
        return_code = process.wait()

    if return_code == 0:
        return_period = avac_p['release']['period_return']
        animation_dir = avac_p['animation']['animation_directory']
        print(f"Creation of the mp4 file: AVAC_animation_for_{avac_p['animation']['variable']}_{return_period}yr.mp4 in the directory {animation_dir}.")
        if avac_p['animation']['making_html']:
            print(f"Creation of the html file: AVAC_animation_for_{avac_p['animation']['variable']}_{return_period}yr.html in the directory {animation_dir}.")
    else:
        print("Failed! See the log file: animation.log.")
    
###################
# post-processing #
###################
fn_eta      = lambda q: q[3,:,:]                     # eta = z_b +h
fn_ground   = lambda q: q[3,:,:] - q[0,:,:]          # z_b
fn_h        = lambda q: q[0,:,:]                     # h
fn_husquare = lambda q: q[1,:,:]**2+q[2,:,:]**2      # h²(u²+v²)
fn_extract  = lambda q: np.array((fn_h(q),fn_eta(q))) # (h, eta)
fn_hu       = lambda q: q[1,:,:]                     # hu
fn_hv       = lambda q: q[2,:,:]                     # hv
fn_u        =  lambda q: np.where(q[0,:,:]>0, (q[1,:,:]/q[0,:,:]), 0)  # u
fn_v        =  lambda q: np.where(q[0,:,:]>0, (q[2,:,:]/q[0,:,:]), 0)  # v    
fn_velocity =  lambda q: np.where(q[0,:,:]>0, np.sqrt((q[2,:,:]/q[0,:,:])**2+(q[1,:,:]/q[0,:,:])**2), 0)  # v 


######################
# initial conditions #
######################

def correctingFactor1(s,theta,nu):
    """
    De Quervain's correction of d_0
    Input: 
        * s: local slope, 
        * theta = critical slope (deg), 
        * nu: de Quervain's coefficient
    Output: correction as multiplying factor
    """
    theta_rad = np.deg2rad(theta) # conversion to radians
    q         = np.arctan(s)      # conversion from slope to angle (radians)
    if q > np.deg2rad(25):
       return (np.sin(theta_rad)-nu*np.cos(theta_rad))/(np.sin(q)-nu*np.cos(q))
    else:
       return 0



def correctingFactor2(z,zref,gradient_hypso):
    """
    Burkard's correction of d_0
    Input: local elevation, zref: elevation of the measurement station
           gradient_hypso: hypsometric gradient (additional snow [m] quantity per 100-m altitude range)
    Output: correction
    """
    return (z-zref)*gradient_hypso/100

##########
# raster #
##########
def extract_values(text):
    """ 
    Goal: extracting the number and word from a string 
    Output: Boolean, number, word, remark
    The Boolean is True when extraction is successful, False otherwise.
    The remark is a text generated when something unusual is met
    """
    # Regular expression to find the first number
    number_pattern = r'-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b'  # Matches integers, floats, and scientific notation
    # Search for the first number
    numbers = re.findall(number_pattern, text)
    num_count = len(numbers)
    number_match = numbers[0]
    # Search for the first word
    word_pattern = r'\b[a-zA-Z_]+\b'  # Matches any word (letters only and underscore)
    # Regular expression to find the first word
    word_match = re.search(word_pattern, text)
    if word_pattern == 'cellsize':
        if num_count > 1:
            remark = "rectangular cells"
        else:
            remark = "square cells"
    else:
        if num_count > 1:
            remark = "more than one value for "+word_match.group()
        else:
            remark = ""
    if number_match and word_match:
        number = number_match # Extract number
        word = word_match.group()
        return True, number, word, remark
    else:
        return False, None, None, "parsing failed"

def count_header_lines(filepath, num_lines=10):
    """
    dertermines the header size of the raster file, i.e.
    the number of lines with alphanumeric information
    Input: file name
    Output: number of lines
    """
    count = 0
    for i in range(1, num_lines + 1):  # Les lignes dans linecache commencent à 1
        line = getline(filepath, i).strip()  # Supprime espaces et \n
        
        # Supprime les nombres (y compris en notation scientifique) au début de la ligne
        cleaned_line = re.sub(r'^[\s\d\.\-+eE]+', '', line).strip()

        # Vérifie s'il reste au moins une lettre dans la ligne
        if re.search(r'[a-zA-Z]', cleaned_line):
            count += 1

    return count

def determine_file_type(file):
    """ 
    Goal: determining the nature of a raster file
        Input: 
            *raster (*.asc)
        Output: 
            * the file type (grass, esri or claw format)
    """
    try:
        with open(file, "r") as file:
            text = file.readline().strip()
        # Regular expression to find the first number
        number_pattern = r'-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b'  # Matches integers, floats, and scientific notation
        # Search for the first number
        number_match = re.search(number_pattern, text)
        # Search for the first word
        word_pattern = r'\b[a-zA-Z_]+\b'  # Matches any word (letters only)
        # Regular expression to find the first word
        word_match = re.search(word_pattern, text)
        start_position = word_match.start() 
        word = word_match.group()
        type_file = 'esri'
        if start_position == 0:
            type_file = 'esri'
        else:
            type_file = 'claw'
        if word in ['north','south','east','west']:
            type_file = 'grass'
        
        if type_file in ['esri','claw','grass']:
            return type_file
        else:
            print(f'Error!I cannot determine the type of the file {file}.')
    except FileNotFoundError:
        print(f"The file '{file}' does not exist.")

# export-to-Qgis function 
def export_raster(fname,tableau,xll,yll,cellsize,ndata=-9999,boolean=False):
    """
    export numpy arrays 'tableau' to file fname in an esri ASCII format
    """
    header =  "ncols        %s\n" % tableau.shape[0]
    header += "nrows        %s\n" % tableau.shape[1]
    header += "xllcorner    %s\n" % xll
    header += "yllcorner    %s\n" % yll
    header += "cellsize     %s\n" % cellsize
    header += "nodata_value %s\n" % ndata
    fmt    = '%1i' if boolean else "%1.2f"
    np.savetxt(fname, np.nan_to_num(tableau.T[::-1,:] ,nan=ndata), header=header, fmt=fmt, comments='')

###################################
# importing raster and shapefiles #
###################################
def reading_raster_file(source, nan_replace = False): 
    '''
    Read raw data from source. The source uses ASCII Grass format (based on cardinal directions). The 
    function reading_raster_file does some work to read and convert these data
    into a format compatible with clawpack
    For more information, see https://www.clawpack.org/grid_registration.html#grid-registration 
    '''
    source = str(source)
    hdr_size = count_header_lines(source, num_lines=10)  # header size
    tab = np.genfromtxt(source, skip_header=hdr_size, missing_values='*' ) 
    if nan_replace: tab = np.nan_to_num(tab,nan=-9999)
    
    hdr = [getline(source, i) for i in range(1, hdr_size+1)]
     
    header_extraction = np.array([extract_values(string) for string in hdr])
    values = [float(val) for val in header_extraction[:,1]]
    keys = header_extraction[:,2]
    type_file = determine_file_type(source)
    if 'xllcenter' in keys:
        grid_type = 'grid'
    else:
        grid_type = 'cell'
    dictionnaire = {keys[k]:values[k] for k in range(0,hdr_size)}
    # DEM extent
    if (type_file == 'grass'):
        ymin = dictionnaire['south']
        ymax = dictionnaire['north']
        xmin = dictionnaire['west']
        xmax = dictionnaire['east']
        nbx  = int(dictionnaire['cols'])
        nby  = int(dictionnaire['rows'])
    if (grid_type == 'cell') and (type_file == 'esri'):
        nbx  = int(dictionnaire['ncols'])
        nby  = int(dictionnaire['nrows'])
        cell_size = dictionnaire['cellsize']
        ymin = dictionnaire['yllcorner']
        ymax = ymin+(nby-1)*cell_size
        xmin = dictionnaire['xllcorner']
        xmax = xmin+(nbx-1)*cell_size
    if (type_file == 'claw'):
        nbx  = int(dictionnaire['ncols'])
        nby  = int(dictionnaire['nrows'])
        cell_size = dictionnaire['cellsize']
        ymin = dictionnaire['ylower']
        ymax = ymin+nby*cell_size
        xmin = dictionnaire['xlower']
        xmax = xmin+nbx*cell_size
    if (grid_type == 'grid') and (type_file == 'esri'):
        nbx  = int(dictionnaire['ncols'])
        nby  = int(dictionnaire['nrows'])
        cell_size = dictionnaire['cellsize']
        ymin = dictionnaire['yllcenter']-cell_size/2
        ymax = ymin+nby*cell_size
        xmin = dictionnaire['xllcenter']-cell_size/2
        xmax = xmin+nbx*cell_size
 
    x = np.linspace(xmin,xmax,nbx)
    y = np.linspace(ymin,ymax,nby)
    X_fine_grid, Y_fine_grid = np.meshgrid(x,y)

    init = topo.Topography()
    init.X = X_fine_grid
    init.Y = Y_fine_grid 
    init.Z = tab[::-1,:]
    init.y = Y_fine_grid[:,0]
    init.x = X_fine_grid[0,:]
    return init

def reading_raster_file_features(source): 
    '''
    Read raster data from source. The source uses ASCII Grass format (based on cardinal directions). The 
    function reading_raster_file extracts information from the header
    For more information, see https://www.clawpack.org/grid_registration.html#grid-registration 
    input: raster file
    output: xmin, xmax, ymin, ymax, nbx, nby, cell_size, dictionnaire, failure, remarks
    '''
    source = str(source)
    hdr_size          = count_header_lines(source, num_lines=10)  # header size
    hdr               = [getline(source, i) for i in range(1, hdr_size+1)]
    header_extraction = np.array([extract_values(string) for string in hdr])
    values            = [float(val) for val in header_extraction[:,1]]
    keys              = header_extraction[:,2]
    type_file = determine_file_type(source)
    remarks   = header_extraction[:,3]
    failure   = header_extraction[:,0]
    if 'xllcenter' in keys:
        grid_type = 'node'
    else:
        grid_type = 'cell'
    dictionnaire = {keys[k]:values[k] for k in range(0,hdr_size)}
    # DEM extent
    if (type_file == 'grass'):
        ymin = dictionnaire['south']
        ymax = dictionnaire['north']
        xmin = dictionnaire['west']
        xmax = dictionnaire['east']
        nbx  = int(dictionnaire['cols'])
        nby  = int(dictionnaire['rows'])
        cell_size = (xmax-xmin)/nbx
    if (grid_type == 'cell') and (type_file == 'esri'):
        nbx  = int(dictionnaire['ncols'])
        nby  = int(dictionnaire['nrows'])
        cell_size = dictionnaire['cellsize']
        ymin = dictionnaire['yllcorner']
        ymax = ymin+(nby-1)*cell_size
        xmin = dictionnaire['xllcorner']
        xmax = xmin+(nbx-1)*cell_size
    if (type_file == 'claw'):
        nbx  = int(dictionnaire['ncols'])
        nby  = int(dictionnaire['nrows'])
        cell_size = dictionnaire['cellsize']
        ymin = dictionnaire['ylower']
        ymax = ymin+nby*cell_size
        xmin = dictionnaire['xlower']
        xmax = xmin+nbx*cell_size
    if (grid_type == 'grid') and (type_file == 'esri'):
        nbx  = int(dictionnaire['ncols'])
        nby  = int(dictionnaire['nrows'])
        cell_size = dictionnaire['cellsize']
        ymin = dictionnaire['yllcenter']-cell_size/2
        ymax = ymin+nby*cell_size
        xmin = dictionnaire['xllcenter']-cell_size/2
        xmax = xmin+nbx*cell_size
    dictionary_extent = {'xmin':xmin,'xmax':xmax,'ymin':ymin,'ymax':ymax,'nbx':nbx,'nby':nby,'cell_size':cell_size,'nodata_value':-9999}

    return xmin, xmax, ymin, ymax, nbx, nby, cell_size, dictionary_extent, failure, remarks, grid_type 

def check_raster(file):
    """
    checks whether 'file' is a raster file
    Input:
        * raster file
    Output: 
        *   True if the file is a raster (or no error has been pinpointed)
            False if import raises problems
    """
    print(f"Raster file: {file}") 
    print()
    if os.path.isfile(file):
        print(f"File {file} exists in the wording directory.")
    print()
    xmin, xmax, ymin, ymax, nbx, nby, cell_size, dico, failure, remarks, grid_type  = \
          reading_raster_file_features(file)
    raster_features = [['xmin',xmin],['xmax',xmax],['ymin',ymin],['ymax',ymax],['nbx',nbx],['nby',nby],['cell size',cell_size]]
    # Check if all strings are empty
    test_all_remark_empty   = np.all(remarks == '')
    test_all_success_import = np.all(failure == 'True')
    if test_all_remark_empty and test_all_success_import:
        print("No problem detected in the raster file")
    elif test_all_success_import:
        # some problems detected
        non_empty_remark = remarks[remarks != '']
        print(f"I detected {len(non_empty_remark )} potential problem(s):")
        for rmk in non_empty_remark:
            print("* ", rmk)
    else:
        print("Check your file! I am not able to import it as a raster file.")
    raster_type = determine_file_type(file)
    print()
    print('Raster features')
    print(f"* The raster format is: {raster_type}.")   
    print(f"* The grid type is: {grid_type}.")      

    # Format the numbers in raster_features
    formatted_raster_features = format_numbers(raster_features)

    # Calculate column widths
    col_width_feature = max(len(row[0]) for row in formatted_raster_features)
    col_width_value = max(len(row[1]) for row in formatted_raster_features)

    # Print the table with custom formatting
    # Print headers
    print()
    print("-" * (col_width_feature + col_width_value + 3))
    print(f"{'Feature':<{col_width_feature}} {'Value':>{col_width_value}}")
    print("-" * (col_width_feature + col_width_value + 3))

    # Print rows
    for feature, value in formatted_raster_features:
        print(f"{feature:<{col_width_feature}} {value:>{col_width_value}}")

    if test_all_success_import: 
        return True
    else:
        return False
    
def export_claw_dem_topotool(xmin,xmax,ymin,ymax,nbx,nby,alt,name_file = 'topography.asc',boolean = False):
    """
    convert the DEM to a claw format and save it.
    Caveat. Consider that this finction uses the '%15.7e' format, and thus the size of the resulting file is large.
    A reduced number of digits may be sufficient. In that case, use export_claw_dem
    Input:
        - xmin,xmax,ymin,ymax : extent of the digital elevation model
        - nbx,nby : numbers of rows and columns
        - alt: matrix of elevation
        - name_file: name of the file to which the data are exported
        - boolean: if true, exports only 0 or 1 (to create a mask)
    output:
        - raster file 'name_file' compatible with clawpack (topotype = 3)
    """
    print(f'Export of DEM to file {name_file}.')
    x = np.linspace(xmin,xmax,nbx)
    y = np.linspace(ymin,ymax,nby)
    X_fine_grid, Y_fine_grid = np.meshgrid(x,y)

    init = topo.Topography()
    init.X = X_fine_grid
    init.Y = Y_fine_grid 
    init.Z = alt
    init.y = Y_fine_grid[:,0]
    init.x = X_fine_grid[0,:]
    if boolean:
	    init.write(name_file,topo_type=3, Z_format='%1i')
    else:
        init.write(name_file,topo_type=3)

def export_claw_dem(xmin,xmax,ymin,ymax,nbx,nby,alt,name_file = 'topography.asc',boolean = False,
                    Z_format='%9.1f',Language = 'French'):
    """
    convert the DEM to a claw format and save it (clawpack topo type 3).
    Context: this function provides raster files ~40 % smaller than the clawpack default '%15.7e'.
    Use '%1i' (boolean=True) for integer masks.
    Input:
        - xmin,xmax,ymin,ymax : extent of the digital elevation model
        - nbx,nby : numbers of rows and columns
        - alt: matrix of elevation
        - name_file: name of the file to which the data are exported
        - boolean: if true, exports only 0 or 1 (to create a mask)
        - Z_formaz: controls the ASCII format of elevation values. 
          Default '%9.1f' (10 cm precision) is adequate for LiDAR DEMs and yields files
    Output:
        - raster file 'name_file' compatible with clawpack (topotype = 3)
    """
    if Language == 'French':
        print(f'* Export du MNT vers le raster {name_file}.')
    else:
        print(f'* Export of DEM to file {name_file}.')
    cell_size    = (xmax - xmin) / (nbx - 1)
    no_data      = -9999
    cell_size_y  = (ymax - ymin) / (nby - 1)
    deviation    = abs((cell_size-cell_size_y)/cell_size)
    if deviation > 0.01: 
            if Language == 'French':
                print(f"* Attention, je trouve dx = {cell_size:.2f} m et dy = {cell_size_y:.2f} m.")
            else:
                print(f"* Caveat: I found dx = {cell_size:.2f} m and dy = {cell_size_y:.2f} m.")
    Z = np.where(np.isnan(alt), no_data, alt)
    num_nan = np.isnan(alt).sum()
    if num_nan > 0:
        if Language == 'French':
            print(f'* Z contient {num_nan} valeurs non numériques (nan), remplacées par {no_data}.')
        else:
            print(f'* Z contains {num_nan} nan values, replacing with {no_data}.')

    fmt = '%1i' if boolean else Z_format

    with open(name_file, 'w') as f:
        # geoclaw type-3 header (value first, then label)
        f.write('%6i                              ncols\n'  % nbx)
        f.write('%6i                              nrows\n'  % nby)
        f.write('%22.15e              xlower\n'             % xmin)
        f.write('%22.15e              ylower\n'             % ymin)
        f.write('%22.15e              cellsize\n'           % cell_size)
        f.write('%10i                          nodata_value\n' % no_data)
        # data: one row per line, top row first (numpy.savetxt is C-level, ~50× faster than a Python loop)
        np.savetxt(f, np.flipud(Z), fmt=fmt)

def export_claw_dem_window(topo_file, window, name_file='topography_window.asc'):
    """
    Export a raster corresponding to windiw

    Input
    * topo_file: topo object
    * window : (xmin_window, ymin_window, xmax_window, ymax_window)
      The coordinates are snapped to the nearest grid nodes        
    * name_file: output file name (default : 'topography_window.asc')
    """
    xmin_w, ymin_w, xmax_w, ymax_w = window

    ix = np.where((topo_file.x >= xmin_w) & (topo_file.x <= xmax_w))[0]
    iy = np.where((topo_file.y >= ymin_w) & (topo_file.y <= ymax_w))[0]

    if ix.size == 0 or iy.size == 0:
        raise ValueError("The requested window is outside or does not contain any points from the raster.")

    Z_window = topo_file.Z[np.ix_(iy, ix)]
    xmin_out, xmax_out = topo_file.x[ix[0]],  topo_file.x[ix[-1]]
    ymin_out, ymax_out = topo_file.y[iy[0]],  topo_file.y[iy[-1]]
    nbx_out, nby_out   = len(ix), len(iy)

    print(f'Export of windowed DEM to file {name_file}.')
    print(f'  x : [{xmin_out:.1f}, {xmax_out:.1f}]  ({nbx_out} cols)')
    print(f'  y : [{ymin_out:.1f}, {ymax_out:.1f}]  ({nby_out} rows)')

    export_claw_dem(xmin_out, xmax_out, ymin_out, ymax_out,
                    nbx_out, nby_out, Z_window, name_file)

def plot_topo(topo_file, ax=None, figsize_width=10, contour_interval=25,
              azdeg=315, altdeg=45, step = 200,ylabel_position="left",resampling=None):
    """
    Draws the topographic background (hillshade + contour lines) on a matplotlib axis.

    If ax is None, create a new figure with dimensions suitable for the raster. The axis ticks should align with multiples of 100 m (absolute coordinates).

    Input:
        * topo_file        : object returned by reading_raster_file (Digital Elevation Model, DEM)
        * ax               : existing matplotlib axis (optional; if None, a figure is created)
        * figsize_width    : width of the figure in inches if ax=None (default is 10)
        * contour_interval : contour line spacing in meters (default is 25)
        * azdeg, altdeg    : azimuth and elevation of the light source for the hillshade
        * step             : step between labels, default is 200 m
        * ylabel_position  : position of the y-labels
        * resampling       : integer or None. If an integer is given, the DEM is resampled with a step = resampling

    Output:
        * fig, ax, x0, y0  (where x0, y0: southwest corner of the raster in absolute coordinates)
    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import math

    x0 = float(topo_file.x[0])
    y0 = float(topo_file.y[0])
    dx = float(topo_file.x[-1] - topo_file.x[0])
    dy = float(topo_file.y[-1] - topo_file.y[0])

    if ax is None:
        w = figsize_width
        h = round(w * dy / dx, 2)
        fig, ax = plt.subplots(figsize=(w, h), layout='constrained')
        try:
            fig.canvas.header_visible = False   # ipympl uniquement
        except AttributeError:
            pass
    else:
        fig = ax.figure

    Z = topo_file.Z
    nrows, ncols = Z.shape
    if ncols != len(topo_file.x) or nrows != len(topo_file.y):
        # Z a été rééchantillonné sans mettre à jour x/y : on recalcule la grille depuis Z.shape
        x_rel = np.linspace(0, float(topo_file.x[-1] - topo_file.x[0]), ncols)
        y_rel = np.linspace(0, float(topo_file.y[-1] - topo_file.y[0]), nrows)
    else:
        x_rel = topo_file.x - x0
        y_rel = topo_file.y - y0
    XX, YY = np.meshgrid(x_rel, y_rel)

    # --- hillshade ---
    ls = mcolors.LightSource(azdeg=azdeg, altdeg=altdeg)
    cell_size = float(x_rel[1] - x_rel[0])
    hs = ls.hillshade(Z, vert_exag=2, dx=cell_size, dy=cell_size)
    if resampling is None:
        ax.pcolormesh(XX, YY, hs, cmap="gray", shading="auto", alpha=0.8)
    else:
        ax.pcolormesh(XX[::resampling,::resampling], YY[::resampling,::resampling], hs[::resampling,::resampling], cmap="gray", shading="auto", alpha=0.8)

    # --- courbes de niveau ---
    zmin_c = int(np.nanmin(Z) // contour_interval) * contour_interval
    zmax_c = int(np.nanmax(Z) // contour_interval + 1) * contour_interval
    levels_minor = np.arange(zmin_c, zmax_c, contour_interval)
    levels_major = np.arange(zmin_c, zmax_c, contour_interval * 4)

    ax.contour(XX, YY, Z, levels=levels_minor, colors="k", linewidths=0.4, alpha=0.5)
    cs = ax.contour(XX, YY, Z, levels=levels_major, colors="k", linewidths=0.9, alpha=0.8)
    ax.clabel(cs, fmt="%d m", fontsize=8, inline=True)

    ax.set_aspect("equal")

    # --- graduations sur multiples de 100 m (coordonnées absolues) ---
    
    x_ticks = np.arange(math.ceil(x0 / step) * step, x0 + dx + step, step) - x0
    y_ticks = np.arange(math.ceil(y0 / step) * step, y0 + dy + step, step) - y0
    x_ticks = x_ticks[(x_ticks >= 0) & (x_ticks <= dx)]
    y_ticks = y_ticks[(y_ticks >= 0) & (y_ticks <= dy)]
    ax.set_xticks(x_ticks)
    ax.set_yticks(y_ticks)

    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v + x0:.0f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v + y0:.0f}"))
    if ylabel_position=='right':
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")    
    else:
        ax.yaxis.tick_left()
        ax.yaxis.set_label_position("left") 
    ax.tick_params(axis="y", labelrotation=90)
    ax.set_xlabel(r"$x$  [m]")
    ax.set_ylabel(r"$y$  [m]")
    ax.grid(linewidth=0.7, alpha=0.85)

    return fig, ax, x0, y0


class WindowSelector:
    """
    Interactive tool for defining a rectangular window on a topographic plot.

    Requires an interactive matplotlib backend. In the notebook, run the following beforehand:
    %matplotlib widget          (requires ipympl)
    or
    %matplotlib notebook        (legacy backend)

    Usage:
    -----
    sel = WindowSelector(topo_file)
    -----
    it draws a rectangle by clicking and dragging, which can be adjusted with the handles.
    sel.window provides the coordinates (xmin, ymin, xmax, ymax) of the window
    """

    def __init__(self, topo_file, figsize_width=10, contour_interval=25,
                 azdeg=315, altdeg=45, language='English', line=[], step = 100):
        import matplotlib.pyplot as plt
        from matplotlib.widgets import RectangleSelector

        if language == 'French':
            print("Cliquer-glisser pour délimiter la fenêtre. "
                  "Ajuster avec les poignées.  ")
        else:
            print("Click and drag to define the window. "
                  "Adjust using the handles.  ")

        self.window = None

        self._fig, ax, self._x0, self._y0 = plot_topo(
            topo_file, figsize_width=figsize_width,
            contour_interval=contour_interval, azdeg=azdeg, altdeg=altdeg, step = step)

        if len(line) >= 2:
            ax.plot([line[0][0] - self._x0, line[1][0] - self._x0],
                    [line[0][1] - self._y0, line[1][1] - self._y0],
                    color='black')

        self._selector = RectangleSelector(
            ax,
            self._on_select,
            useblit=False,
            button=[1],
            minspanx=1,
            minspany=1,
            spancoords="data",
            interactive=True,
            props=dict(facecolor="tomato", edgecolor="red", alpha=0.25, fill=True),
            handle_props=dict(markersize=6),
        )
        plt.show()

    def _on_select(self, eclick, erelease):
        # Les coords du sélecteur sont relatives. Reconversion en absolu
        xmin = self._x0 + min(eclick.xdata, erelease.xdata)
        xmax = self._x0 + max(eclick.xdata, erelease.xdata)
        ymin = self._y0 + min(eclick.ydata, erelease.ydata)
        ymax = self._y0 + max(eclick.ydata, erelease.ydata)
        self.window = (xmin, ymin, xmax, ymax)
        print(
            f"\rFenêtre : window = ({xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f})   ",
            end="",
            flush=True,
        )

def export_claw_initiation_file(topo_file,zi,filename='init.xyz'):   
    """
    save the initiation file as topotype-1 file
    Input: topo_file, zi
    optional argument:filename
    """
    print(f'Export of initial conditions to file init.xyz.')   
    init   = topo.Topography()
    init.X = topo_file.X 
    init.Y = topo_file.Y 
    init.Z = zi[:,:] 
    init.y = init.Y[:,0]
    init.x = init.X[0,:]
    init.write(filename,topo_type=1)
    print(f'* maximum initial depth of starting zone  = {np.max(zi[:,:])} m')    

def test_keys(dictionary_tested,dictionary_ref):
    """ 
    checks whether all the keys are defined in the loaded dictionary 
    """
    if not isinstance(dictionary_ref, dict):
        dictionary_ref = {key: None for key in dictionary_ref}
    if not sorted(list(dictionary_tested.keys()) )==sorted(list(dictionary_ref.keys()) ):
        print('The configuration file does not satisfy the requirements.')
        difference_1 = set(dictionary_ref.keys())-set(dictionary_tested.keys())
        difference_2 = set(dictionary_tested.keys())-set(dictionary_ref.keys())
        if len(difference_1)>0:
            print(f"There is missing information. Please check your configuration file. Computation will fail otherwise!")
            for info in difference_1: print(f"* Missing key: {info}")
            return 1
        if len(difference_2)>0:
            print(f"There is additional information. This information will not be used here.")
            for info in difference_2: print(f"* Additional key: {info}")
            return 0
    else:
        return 0

def import_initial_condition(file):
    """"
    imports the starting-area shapefile.
    input: file name
    output: geopandas frame (set of polygons), number of polygons
    """
    areas = gp.read_file(file)
    nb_areas = len(areas)
    print(f"There are {nb_areas} starting area(s) in the file {file}.")

    # determine the CRS of the GeoDataFrame
    crs = areas.crs

    # Print the CRS information
    print("Coordinate Reference System (CRS) of the shapefile:", crs)

    # Extract the EPSG code (if available)
    if crs is not None:
        epsg_code = crs.to_epsg()
        if epsg_code is not None:
            print("EPSG code of the shapefile:", epsg_code)
        else:
            print("The CRS does not have an EPSG code, or it is not recognized.")
    else:
        print("The shapefile does not have a defined CRS.")
    return areas, nb_areas 

###########
# testing #
###########

def import_configuration_files(file_name):
    """
    import the configuration and check consistency
    output: a dictionary with AVAC parameters
    the script can pinpoint potential errors in the parameters
    """
    print(f"Opening the configuration file {file_name}...")

    with open(file_name, 'r') as file:
        avac_parameters = yaml.safe_load(file)

    def is_genuine_int(var):
        return isinstance(var, int) and not isinstance(var, bool)    

    def is_integer(key_1,key_2):
        """check whether avac_parameters[key_1][key_2] is integer"""
        var = avac_parameters[key_1][key_2]
        if not is_genuine_int(var):
            print(f"The variable {key_1}.{key_2} must be an integer! Here, I get {key_1}.{key_2} = {var}")
            return 1
        else:
            return 0

    def is_boolean(key_1,key_2):
        """checks whether avac_parameters[key_1][key_2] is boolean"""
        var = avac_parameters[key_1][key_2]
        if not isinstance(var, bool):
            print(f"The variable {key_1}.{key_2} must be a Boolean! Here, I get {key_1}.{key_2} = {var}")
            return 1
        else:
            return 0
    topo_source = avac_parameters['topography']['topo_source']
    topo_dir    = avac_parameters['computation']['topo_dir']

    keys_avac          = ['computation', 'release', 'rheology', 'topography','output','animation','date','objects']
    keys_comput_virtual= ['cfl_max', 'cfl_target', 'dry_limit', 'max_iter', 'nb_simul', \
                        'refinement', 't_max','cell_size','boundary','output_directory', \
                        'boundary_west','boundary_east','boundary_south','boundary_north', \
                        'xlower','xupper','ylower','yupper', 'dx','dy','limiter', \
                        'track_mass', 'mass_frac_stop', 'force_stop']
    keys_comput_real   = ['cfl_max', 'cfl_target', 'dry_limit', 'max_iter', 'nb_simul', \
                        'refinement', 't_max','cell_size','boundary','output_directory','topo_dir']
    keys_release       = ['correction_elevation', 'correction_slope', 'd0', 'gradient_hypso', 'nu', 'theta_cr', 'z_ref',  'period_return']
    keys_rheology      = ['beta', 'model', 'mu', 'rho', 'u_cr', 'xi']
    keys_topography    = ['dem', 'starting_areas','finer_dem','topo_refinement','topo_source']    
    keys_output        = ['output_format', 'verbosity', 'delta_t']
    keys_animation     = ['n_out','variable']
    keys_objects       = ['line']
    rheological_models = ['Voellmy','Coulomb']
    output_formats     = ['ascii','binary32','binary64']
    verbosity_formats  = [0,1,2,3,4] # see https://www.clawpack.org/pyclaw/output.html
    boundary_formats   = ['wall','extrap','user']
    animation_formats   = ['pressure','depth','velocity']

    keys_computation =  keys_comput_real if topo_source == 'real_world' else keys_comput_virtual

    error = 0
    error += test_keys(avac_parameters,keys_avac) # check whether the config file keys are those expected

    print()
    # Checs topography
    error += test_keys(avac_parameters['topography'],keys_topography)
    file_path = Path(topo_dir) / avac_parameters['topography']['dem']
    topo_refinement = avac_parameters['topography']['topo_refinement']
    if file_path.exists():
        print(f"- I found the DEM file {file_path}.")
    test_success = [bool(chain) for chain in reading_raster_file_features(file_path)[8] ]
    if np.all(np.array(test_success)):
        print("  File import raises no issue.")
    else:
        print(f"  When importing file {avac_parameters['topography']['dem']} from {topo_dir}, I found errors in the header. Please check.")
        error += 1
    if topo_refinement:
        fine_topo_path = Path(topo_dir) / avac_parameters['topography']['finer_dem']
        if fine_topo_path.exists():
            print(f"- Finer topography: I found the DEM file {fine_topo_path} in the directory {topo_dir}.")
        test_success = [bool(chain) for chain in reading_raster_file_features(fine_topo_path)[8] ]
        if np.all(np.array(test_success)):
            print("  File import raises no issue.")
        else:
            print(f"  When importing file {avac_parameters['topography']['finer_dem']}, I found errors in the header. Please check.")
            error += 1


    file_path = avac_parameters['topography']['starting_areas']
    if file_path is None:
        print("- No starting areas shapefile specified (starting_areas is null).")
    else:
        if os.path.isfile(file_path):
            print(f"- I found the shapefile {file_path} containing the starting areas.")
            print(f"  It seems ok.")
        else:
            print(f"- I failed to import {file_path}! Please check.")
            error += 1
        file_path = avac_parameters['topography']['starting_areas'][:-3]+'shx'
        if not os.path.isfile(file_path):
            print(f"- File {file_path} is missing! Please check. ")
            print(f"  This file accompanies the shapefile. Find it or reconstruct it using gdal. ")
            error +=1
    # checks output
    error += test_keys(avac_parameters['output'],keys_output)
    error += is_integer('output','verbosity')
    if avac_parameters['output']['output_format'] not in output_formats:
        print(f"The output format {avac_parameters['output']['output_format'] } is unknown!")
        print("The only current possibilities are: 'ascii', 'binary64' or 'binary32'.")
    if avac_parameters['output']['verbosity'] not in verbosity_formats:
        print(f"The verbosity parameter is set to {avac_parameters['output']['verbosity'] }.")
        print("It should range from 0 to 4.")
    if avac_parameters['output']['delta_t'] > avac_parameters['computation']['t_max']:
        print(f"The parameter delta_t is set to {avac_parameters['output']['delta_t'] }.")
        print(f"It is larger to t_max = {avac_parameters['computation']['t_max'] }!")
        print("I correct it. Check!")
        avac_parameters['output']['delta_t'] = avac_parameters['computation']['t_max']
    # checks computation parameters
    error += test_keys(avac_parameters['computation'],keys_computation)
    if (avac_parameters['computation']['cfl_max']>1) or (avac_parameters['computation']['cfl_max']<0):
        print(f"Check variable cfl_max = {avac_parameters['computation']['cfl_max']}")
        print(f"This value should be an integer in the 0.1-1 range.")
        error += 1
    if (avac_parameters['computation']['cfl_target']>avac_parameters['computation']['cfl_max']):
        print(f"Check variable cfl_target = {avac_parameters['computation']['cfl_max']}")
        print(f"This value cannot be larger car cfl_max = {avac_parameters['computation']['cfl_max']}.")
        error += 1
    error += is_integer('computation','max_iter')
    error += is_integer('computation','nb_simul')
    error += is_integer('computation','refinement')
    if (avac_parameters['computation']['refinement']<1) or (avac_parameters['computation']['refinement']>6):
        print(f"Check variable refinement = {avac_parameters['computation']['refinement']}.")
        print(f"This value should be an integer in the 1-6 range.")
    if topo_source == 'real_world':
        if avac_parameters['computation']['boundary'] not in boundary_formats:
            print(f"The boundary condition {avac_parameters['computation']['boundary'] } is unknown!")
            print("The only current possibilities are: 'ascii', 'binary64' or 'binary32'.")
        if avac_parameters['computation']['boundary'] == 'user':
            print("This is not implemented by default. Check file bc2.f90.")
    else:
        if avac_parameters['computation']['boundary_south'] not in boundary_formats:
            print(f"The boundary condition {avac_parameters['computation']['boundary_south'] } is unknown!")
            print("The only current possibilities are: 'ascii', 'binary64' or 'binary32'.")
        if avac_parameters['computation']['boundary_south'] == 'user':
            print("This is not implemented by default. Check file bc2.f90.")
    # check release parameters
    error += test_keys(avac_parameters['release'],keys_release)
    error += is_boolean('release','correction_elevation')
    error += is_boolean('release','correction_slope')
    if (avac_parameters['release']['gradient_hypso']<0) or (avac_parameters['release']['gradient_hypso']>0.2):
        print(f"Check variable gradient_hypso = {avac_parameters['release']['gradient_hypso']}.")
        print(f"This value cannot be negative or larger than 20 cm/100 m.")
        error += 1
    if (avac_parameters['release']['z_ref']<0) or (avac_parameters['release']['z_ref']>9000):
        print(f"Check variable z_ref = {avac_parameters['release']['z_ref']}.")
        print(f"This value cannot be negative or larger than 9000 m.")
        error += 1
    if (avac_parameters['release']['theta_cr']<5) or (avac_parameters['release']['theta_cr']>50):
        print(f"Check variable theta_cr = {avac_parameters['release']['theta_cr']}.")
        print(f"This value should be expressed in degrees and close to 30.")
        error += 1
    # check animation
    error += test_keys(avac_parameters['animation'],keys_animation)
    error += is_integer('animation','n_out')
    if avac_parameters['animation']['variable'] not in animation_formats:
        print(f"The variable {avac_parameters['animation']['variable'] } for animation is unknown!")
        print("The only current possibilities are: 'pressure', 'depth' or 'velocity'.")
    # check rheology parameters
    error += test_keys(avac_parameters['rheology'],keys_rheology)
    if avac_parameters['rheology']['model'] not in rheological_models:
        print(f"The rheological model {avac_parameters['rheology']['model'] } is unknown!")
        print("The only current possibilities are: 'Voellmy' or 'Coulomb'.")
    mu_vals = avac_parameters['rheology']['mu']
    if not isinstance(mu_vals, list):
        mu_vals = [mu_vals]
    for mu_v in mu_vals:
        if (mu_v < 0.05) or (mu_v > 0.5):
            print(f"Check variable mu = {mu_v}.")
            print(f"This value should be in the 0.05-0.5 range.")
            error += 1
    xi_vals = avac_parameters['rheology']['xi']
    if not isinstance(xi_vals, list):
        xi_vals = [xi_vals]
    for xi_v in xi_vals:
        if (xi_v < 100) or (xi_v > 1e4):
            print(f"Check variable xi = {xi_v}.")
            print(f"This value should be in the 100-10,000 range.")
    if (avac_parameters['rheology']['u_cr']<0) or (avac_parameters['rheology']['u_cr']>0.5):
        print(f"Check variable u_cr = {avac_parameters['rheology']['u_cr']}.")
        print(f"This value should be in the 0-0.5 range.")
        error += 1
    if (avac_parameters['rheology']['rho']<100) or (avac_parameters['rheology']['rho']>1000):
        print(f"Check variable rho = {avac_parameters['rheology']['rho']}.")
        print(f"This value should be in the 100-1000 range.")
        error += 1
    if (avac_parameters['rheology']['beta']<0) or (avac_parameters['rheology']['u_cr']>1.5):
        print(f"Check variable beta = {avac_parameters['rheology']['beta']}.")
        print(f"This value should be in the 0-1.5 range.")
        error += 1
    print()    
    if error>0:
        print(f"Error(s) detected: {error}")
    else:
        print("Everything looks fine so far...")
    print()
    # Flatten the configuration dictionary
    flat_configuration = flatten_dict(avac_parameters)

    print("Configuration file:")
    for key, value in flat_configuration.items():
        var_name = key.replace('.', '_')
        globals()[var_name] = value
        print(f"* {var_name} = {value}")
    return avac_parameters

def create_cross_section(dem, x_coords, y_coords, profile_coords, num_points=1000):
    from scipy.interpolate import RegularGridInterpolator
    from scipy.spatial.distance import cdist
    """
    Create a cross-section along a polyline. Originally made for plotting DEM cross-sections, but it works
    for other two-dimensional data.
    
    Input:
        * dem: masked array of DEM
        * x_coords: x coordinates of DEM grid
        * y_coords: y coordinates of DEM grid
        * rofile_coords: array of (x,y) coordinates along the profile
        * num_points: number of points to sample along the profile
    Output:
        * sampling_distances: distane from the origin point
        * elevations: array of elevation along the polyline
        * sampled_points: coordinates of points (if needed)
    """
    
    # Create interpolator for DEM
    # Use np.ma.filled so that masked cells become NaN rather than being
    # interpolated from the raw fill value (-2e99 for fgmax never-wet cells).
    dem_data = np.ma.filled(dem, np.nan) if np.ma.is_masked(dem) else np.asarray(dem)
    interp = RegularGridInterpolator((y_coords, x_coords), dem_data,
                                    bounds_error=False, fill_value=np.nan)
    
    # Calculate cumulative distance along the profile
    profile_coords = np.array(profile_coords)
    segments = np.diff(profile_coords, axis=0)
    segment_lengths = np.sqrt(np.sum(segments**2, axis=1))
    cumulative_distances = np.insert(np.cumsum(segment_lengths), 0, 0)
    total_length = cumulative_distances[-1]
    
    # Create sampling distances along the entire profile
    sampling_distances = np.linspace(0, total_length, num_points)
    
    # Interpolate points along the entire profile
    sampled_points = []
    for dist in sampling_distances:
        # Find which segment this distance falls into
        segment_idx = np.searchsorted(cumulative_distances, dist, side='right') - 1
        segment_idx = min(segment_idx, len(segments) - 1)
        
        # Calculate position within the segment
        segment_start_dist = cumulative_distances[segment_idx]
        segment_progress = dist - segment_start_dist
        segment_frac = segment_progress / segment_lengths[segment_idx]
        
        # Interpolate coordinates
        start_point = profile_coords[segment_idx]
        end_point = profile_coords[segment_idx + 1]
        point = start_point + segment_frac * (end_point - start_point)
        sampled_points.append(point)
    
    sampled_points = np.array(sampled_points)
    
    # Extract elevations at sampled points
    elevations = interp(sampled_points[:, [1, 0]])  # Note: y,x order for RegularGridInterpolator
    
    return sampling_distances, elevations, sampled_points

def import_polylines(file='profil.shp',Language = 'English'):
    """ import a polyline and describes its features.
    Input:
        * file: name of the shapefile
    Output:
        * ligne: geopandas object
        * coords_array: coordinates of the points
    """
    import geopandas as gp
    # Read the shapefile
    ligne = gp.read_file(file)
    text3 = {'English':f"Consider providing a shapefile with a single polyline...",
             'French':f"Il faut fournir un shapele avec une seule polyligne !"}
    text4 = {'English':f"Coordinates array shape:",
             'French':f"Dimensions du vecteur (array) des coordonnées : "}
    text5 = {'English':f"Error... No data found!",
             'French':f"Erreur... Pas de données !"}
    # Extract coordinates from the geometry
    if len(ligne) > 0:
        # Get the first (and probably only) geometry
        geometry = ligne.geometry.iloc[0]

        # Extract coordinates
        if geometry.geom_type == 'LineString':
            coords = np.array(geometry.coords)
            text1 = {'English':f"I import a LineString object with {len(coords)} points",
                     'French':f"J'importe la polyline composée de {len(coords)} points"}
            print(text1[Language])
            for i in range(len(coords)): print(f"Point {i}: Coordinates x = {coords[i,0]:.1f} m and y = {coords[i,1]:.1f} m")

        elif geometry.geom_type == 'MultiLineString':
            # For MultiLineString, we will have trouble...
            coords = []
            for line in geometry.geoms:
                coords.extend(list(line.coords))
            text2 = {'English':f"I found a MultiLineString with {len(coords)} as the total number of points.",
                     'French':f"J'ai trouvé un objet MultiLineString composé en tout de {len(coords)} points"}
            print(text2[Language])
            print(text3[Language])
            
        # Convert to numpy array for easier manipulation
        coords_array = np.array(coords)
        print(text4[Language], coords_array.shape)
    else:
        print(text5[Language])
    return ligne, coords_array

def reload_avac(dossier=None):
    """
    Reloads the module module_avac in a robust way... so if changes are made in this file, it is possible to reload the module.

    Input:
        * folder : str, optional. Path to the folder containing the module

    Output:
        * module or None. The reloaded module or None in case of error

    """
    import importlib
    import os
    # Chemin explicite
    if dossier is None:
        module_dir = os.getcwd()
    else:
        module_dir = dossier
    
    module_path = os.path.join(module_dir, 'module_avac.py')
    
    # Vérification de l'existence du fichier
    if not os.path.exists(module_path):
        print(f"Error: {module_path} does not exist...")
        return None
    
    try:
        # Add folder to system path
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        
        # Méthode 1: if module has not been imported
        if 'module_avac' not in sys.modules:
            spec = importlib.util.spec_from_file_location("module_avac", module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["module_avac"] = module
            spec.loader.exec_module(module)
            print("Module imported for the first time.")
        
        # Méthode 2: if module exists, reload it
        else:
            # Supprimer complètement le module du cache
            if 'module_avac' in sys.modules:
                del sys.modules['module_avac']
            
            # Nettoyer aussi les sous-modules si ils existent
            modules_to_remove = [name for name in sys.modules.keys() 
                               if name.startswith('module_avac.')]
            for module_name in modules_to_remove:
                del sys.modules[module_name]
            
            # Reimporter complètement
            spec = importlib.util.spec_from_file_location("module_avac", module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["module_avac"] = module
            spec.loader.exec_module(module)
            print("Module reloaded successfully.")
        
        # Mettre à jour les globals() du notebook
        globals()['module_avac'] = sys.modules['module_avac']
        
        return sys.modules['module_avac']
        
    except Exception as e:
        print(f"ERROR when loading the module: {e}")
        return None
    
def export_profile(file,distances,elevations,header=False):
    # export of the profile
    with open(file, 'w') as f:
        if header: f.write('distance\televation\n')  # header
        for dist, elev in zip(distances, elevations):
            f.write(f'{dist}\t{elev}\n')

def format_m(x, decimals=1):
    """espace fine insécable"""
    return f"{x:_.{decimals}f}".replace("_", "\u202f")   

def rename_output_directory(config, current_directory, Change_output_directory_name=False, Overwrite_directory=False):
    """
    Rename output directory from '_output' to the name in the output dictionary (if existing).
    Input:
        * config: the configuration dictionary
        * current_directory: Path object
        * Change_output_directory_name: boolean (False by default) 
        * Overwrite_directory: boolean (False by default
    """
    from pathlib import Path
    output = config['output']
    if Change_output_directory_name:
        print("Changing the name of the output directory")
        if 'output_directory' in output:
            output_dir_target = current_directory / output['output_directory']
            output_dir        = current_directory / '_output'
            print(f"target directory:{output_dir_target}")
            print(f"current directory:{output_dir}")
            if output['output_directory'] != '_output':
                if output_dir.exists():
                    if output_dir_target.exists():
                        print(f"Directory {output_dir_target} already existing")
                        if Overwrite_directory:
                            import shutil
                            print("I will erase it")
                            shutil.rmtree(output_dir_target)
                            output_dir.rename(output_dir_target)
                        else:
                            print("Nothing to be done. I keep the existing directory.")
                    else:
                        output_dir.rename(output_dir_target)
                else:
                    print("Error: the directory '_output' is missing!")
            else:
                print(f"Ckeck the output dictionary. As output['output_directory'] is '_output, no change is needed.")
        else:
            print("there is no key called 'output_directory' in the output dictionary")
    else:
        print("The output directory name is '_output'")
