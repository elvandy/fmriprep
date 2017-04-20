#!/usr/bin/env python
# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""
Created on Wed Dec  2 17:35:40 2015

@author: craigmoodie
"""
from __future__ import print_function, division, absolute_import, unicode_literals

import os
from copy import deepcopy

from nipype.pipeline import engine as pe
from nipype.interfaces import utility as niu

from fmriprep.interfaces import BIDSDataGrabber, BIDSFreeSurferDir
from fmriprep.utils.misc import collect_bids_data, get_biggest_epi_file_size_gb

from fmriprep.workflows.anatomical import init_anat_preproc_wf

from fmriprep.workflows.epi import init_func_preproc_wf

from bids.grabbids import BIDSLayout


def init_fmriprep_wf(subject_list, task_id, settings, run_uuid):
    workflow = pe.Workflow(name='fmriprep_wf')

    if settings.get('freesurfer', False):
        fsdir = pe.Node(
            BIDSFreeSurferDir(
                derivatives=settings['output_dir'],
                freesurfer_home=os.getenv('FREESURFER_HOME'),
                spaces=settings['output_spaces']),
            name='fsdir')

    for subject in subject_list:
        generated_workflow = base_workflow_generator(subject, task_id=task_id,
                                                     settings=settings)
        if generated_workflow:
            generated_workflow.config['execution']['crashdump_dir'] = (
                os.path.join(settings['output_dir'], "fmriprep", "sub-" + subject, 'log', run_uuid)
            )
            for node in generated_workflow._get_all_nodes():
                node.config = deepcopy(generated_workflow.config)
            if settings.get('freesurfer', False):
                workflow.connect(fsdir, 'subjects_dir',
                                 generated_workflow, 'inputnode.subjects_dir')
            else:
                workflow.add_nodes([generated_workflow])

    return workflow


def base_workflow_generator(subject_id, task_id, settings):
    subject_data = collect_bids_data(settings['bids_root'], subject_id, task_id)

    settings["biggest_epi_file_size_gb"] = get_biggest_epi_file_size_gb(subject_data['func'])

    if subject_data['func'] == []:
        raise Exception("No BOLD images found for participant {} and task {}. "
                        "All workflows require BOLD images.".format(
                            subject_id, task_id if task_id else '<all>'))

    if subject_data['t1w'] == []:
        raise Exception("No T1w images found for participant {}. "
                        "All workflows require T1w images.".format(subject_id))

    return init_basic_wf(subject_data, settings, name=subject_id)


def init_basic_wf(subject_data, settings, name='basic_wf'):
    """
    The main fmri preprocessing workflow, for the ds005-type of data:

      * Has at least one T1w and at least one bold file (minimal reqs.)
      * No SBRefs
      * May have fieldmaps

    """

    if settings is None:
        settings = {}

    workflow = pe.Workflow(name=name)

    if subject_data['func'] == ['bold_preprocessing']:
        # for documentation purposes
        layout = None
    else:
        layout = BIDSLayout(settings["bids_root"])

    inputnode = pe.Node(niu.IdentityInterface(fields=['subjects_dir']),
                        name='inputnode')

    bidssrc = pe.Node(BIDSDataGrabber(subject_data=subject_data),
                      name='bidssrc')

    # Preprocessing of T1w (includes registration to MNI)
    anat_preproc_wf = init_anat_preproc_wf(name="anat_preproc_wf", settings=settings)

    workflow.connect([
        (inputnode, anat_preproc_wf, [('subjects_dir', 'inputnode.subjects_dir')]),
        (bidssrc, anat_preproc_wf, [('t1w', 'inputnode.t1w'),
                                    ('t2w', 'inputnode.t2w')]),
    ])

    for bold_file in subject_data['func']:
        func_preproc_wf = init_func_preproc_wf(bold_file, layout=layout,
                                               settings=settings)

        workflow.connect([
            (bidssrc, func_preproc_wf, [('t1w', 'inputnode.t1w')]),
            (anat_preproc_wf, func_preproc_wf,
             [('outputnode.bias_corrected_t1', 'inputnode.bias_corrected_t1'),
              ('outputnode.t1_brain', 'inputnode.t1_brain'),
              ('outputnode.t1_mask', 'inputnode.t1_mask'),
              ('outputnode.t1_seg', 'inputnode.t1_seg'),
              ('outputnode.t1_tpms', 'inputnode.t1_tpms'),
              ('outputnode.t1_2_mni_forward_transform', 'inputnode.t1_2_mni_forward_transform')])
        ])

        if settings['freesurfer']:
            workflow.connect([
                (inputnode, func_preproc_wf,
                 [('subjects_dir', 'inputnode.subjects_dir')]),
                (anat_preproc_wf, func_preproc_wf,
                 [('outputnode.subject_id', 'inputnode.subject_id'),
                  ('outputnode.fs_2_t1_transform', 'inputnode.fs_2_t1_transform')]),
            ])

    return workflow
