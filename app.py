from flask import Flask, request, jsonify, send_file
import subprocess
import os
import uuid
import logging
from pathlib import Path
import shutil
import tempfile
import glob
import mimetypes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure temp directory using system's temp directory
TEMP_DIR = Path(tempfile.gettempdir()) / "ffmpeg_api"

def check_disk_space():
    """Check if disk space is available"""
    try:
        total, used, free = shutil.disk_usage(TEMP_DIR)
        free_gb = free // (1024 * 1024 * 1024)  # Convert to GB
        used_gb = used // (1024 * 1024 * 1024)
        total_gb = total // (1024 * 1024 * 1024)
        
        logger.info(f"Storage stats - Total: {total_gb}GB, Used: {used_gb}GB, Available: {free_gb}GB")
        
        # Warning if less than 10GB free
        if free < (10 * 1024 * 1024 * 1024):  
            logger.warning(f"Low disk space warning. Only {free_gb}GB available")
            
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        pass

def cleanup_old_files():
    """Cleanup any leftover temporary files"""
    try:
        pattern = str(TEMP_DIR / "*")
        for file in glob.glob(pattern):
            try:
                if os.path.isfile(file):
                    os.remove(file)
                    logger.debug(f"Cleaned up old file: {file}")
            except Exception as e:
                logger.error(f"Error cleaning up old file {file}: {e}")
    except Exception as e:
        logger.error(f"Error during old files cleanup: {e}")

def run_with_timeout(cmd, timeout_seconds):
    """Run command with timeout"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds  # Add timeout
        )
        return result
    except subprocess.TimeoutExpired as e:
        logger.error(f"FFmpeg process timed out after {timeout_seconds} seconds")
        raise RuntimeError(f"Video processing timed out after {timeout_seconds} seconds") from e

def create_app():
    """Application factory function"""
    app = Flask(__name__)

    # Initialize temp directory
    try:
        # Ensure directory exists
        TEMP_DIR.mkdir(exist_ok=True, parents=True)
        logger.info(f"Using temporary directory: {TEMP_DIR}")
        
        # Clean up any old files that might have been left
        cleanup_old_files()
        
    except Exception as e:
        logger.error(f"Error during initialization: {e}")

    def cleanup_files(*files):
        """Clean up temporary files"""
        for file in files:
            try:
                if file and os.path.exists(file):
                    os.remove(file)
                    logger.debug(f"Cleaned up temp file: {file}")
            except Exception as e:
                logger.error(f"Error cleaning up {file}: {e}")

    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy", 
            "service": "ffmpeg-api",
            "mode": "development" if app.debug else "production"
        }), 200

    @app.route('/captionize', methods=['POST'])
    def captionize_video():
        """Add ASS subtitles to video using FFmpeg"""
        logger.info("Received captionize request")
        
        # Check available disk space
        check_disk_space()
        
        # Initialize paths as None for cleanup
        video_path = None
        ass_path = None
        output_path = None
        
        try:
            # Validate request files
            if 'input_video_file' not in request.files or 'input_ass_file' not in request.files:
                logger.warning("Missing required files in request")
                return jsonify({
                    "error": "Both video and ASS subtitle files are required",
                    "details": "Use 'input_video_file' for video and 'input_ass_file' for ASS subtitle file. Note: Only .ass subtitle files are supported."
                }), 400

            video_file = request.files['input_video_file']
            ass_file = request.files['input_ass_file']
            custom_command = request.form.get('custom_command', '')

            # Validate file names and types
            if video_file.filename == '':
                return jsonify({"error": "No video file selected"}), 400
            if ass_file.filename == '':
                return jsonify({"error": "No ASS subtitle file selected"}), 400

            # Validate ASS file extension
            if not ass_file.filename.lower().endswith('.ass'):
                return jsonify({
                    "error": "Invalid subtitle file format",
                    "details": "Only .ass subtitle files are supported. Other formats like .srt, .vtt, etc. are not supported."
                }), 400

            # Generate temporary file paths
            temp_id = str(uuid.uuid4())
            video_path = TEMP_DIR / f"video_{temp_id}{Path(video_file.filename).suffix}"
            ass_path = TEMP_DIR / f"sub_{temp_id}.ass"  # Force .ass extension
            output_path = TEMP_DIR / f"output_{temp_id}{Path(video_file.filename).suffix}"

            # Save uploaded files
            logger.info(f"Saving temporary files: {video_path.name}, {ass_path.name}")
            video_file.save(str(video_path))
            ass_file.save(str(ass_path))

            # Change to temp directory to use relative paths
            original_cwd = os.getcwd()
            os.chdir(TEMP_DIR)
            
            try:
                # Use relative paths for FFmpeg
                relative_video = Path(video_path).name
                relative_ass = Path(ass_path).name
                relative_output = Path(output_path).name

                # Construct FFmpeg command with relative paths
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-threads', '2',
                    '-i', relative_video,
                    '-vf', f'ass={relative_ass}',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-crf', '22',
                    '-c:a', 'copy',
                    relative_output
                ]

                # Apply custom FFmpeg parameters if provided
                if custom_command:
                    logger.info(f"Applying custom FFmpeg parameters: {custom_command}")
                    custom_params = custom_command.split()
                    # Insert custom parameters before output file
                    ffmpeg_cmd[-1:] = custom_params + [ffmpeg_cmd[-1]]

                logger.info(f"Executing FFmpeg command: {' '.join(ffmpeg_cmd)}")
                
                # Get FFmpeg timeout from environment
                ffmpeg_timeout = int(os.getenv('FFMPEG_TIMEOUT', 0))  # 0 means no timeout
                
                # Execute FFmpeg with or without timeout
                if ffmpeg_timeout > 0:
                    logger.info(f"Running FFmpeg with {ffmpeg_timeout} seconds timeout")
                    result = run_with_timeout(ffmpeg_cmd, ffmpeg_timeout)
                else:
                    logger.info("Running FFmpeg without timeout")
                    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    logger.error(f"FFmpeg error: {result.stderr}")
                    return jsonify({"error": "FFmpeg processing failed", "details": result.stderr}), 500

                logger.info("Video processing completed successfully")

                # Get the original input filename and create output filename
                original_filename = video_file.filename
                output_filename = f"captioned_{original_filename}"

                # Determine the correct mime type
                mime_type, _ = mimetypes.guess_type(output_filename)
                if not mime_type:
                    mime_type = 'video/mp4'  # Default to video/mp4 if unable to guess

                # Create response using send_file
                response = send_file(
                    str(output_path),
                    mimetype=mime_type,
                    as_attachment=True,
                    download_name=output_filename
                )
                
                # Remove any existing headers we want to control
                if 'Access-Control-Expose-Headers' in response.headers:
                  del response.headers['Access-Control-Expose-Headers']
                if 'Content-Disposition' in response.headers:
                  del response.headers['Content-Disposition']
                # Add headers in specific order
                response.headers['Content-Type'] = mime_type  # Ensure mime type is set
                response.headers['Content-Disposition'] = f'attachment; filename="{output_filename}"'
                response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition'

                return response

            finally:
                # Change back to original directory
                os.chdir(original_cwd)

        except Exception as e:
            logger.exception("Unexpected error during video processing")
            return jsonify({"error": str(e)}), 500

        finally:
            cleanup_files(video_path, ass_path, output_path)

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Global exception handler"""
        logger.exception("Unhandled exception occurred")
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500

    return app

# Create the application instance
app = create_app()

def main():
    """Entry point for local development server"""
    logger.info("Starting development server...")
    logger.info("Note: For production, use Gunicorn via Docker instead")
    app.run(host='0.0.0.0', port=8000, debug=True)

if __name__ == '__main__':
    main()