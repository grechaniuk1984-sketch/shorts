name: Generate Shorts

on:
  workflow_dispatch:
    inputs:
      ids:
        description: "Video ids, e.g. '1 4 7' (empty = all 10)"
        required: false
        default: ""

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install ffmpeg and fonts
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg fonts-dejavu-core
      - run: pip install -r requirements.txt
      - name: Generate videos
        env:
          PIXABAY_API_KEY: ${{ secrets.PIXABAY_API_KEY }}
          PEXELS_API_KEY: ${{ secrets.PEXELS_API_KEY }}
        run: python make_videos.py ${{ github.event.inputs.ids }}
      - uses: actions/upload-artifact@v4
        with:
          name: shorts
          path: output/
          retention-days: 14
