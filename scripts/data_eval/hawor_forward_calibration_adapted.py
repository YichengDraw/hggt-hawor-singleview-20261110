def forward_step(self, batch: Dict, train: bool = False) -> Dict:
    """
    Run a forward step of the network
    Args:
        batch (Dict): Dictionary containing batch data
        train (bool): Flag indicating whether it is training or validation mode
    Returns:
        Dict: Dictionary containing the regression output
    """

    image  = batch['img'].flatten(0, 1)
    center = batch['center'].flatten(0, 1)
    scale  = batch['scale'].flatten(0, 1)
    img_focal = batch['img_focal'].flatten(0, 1)
    img_center = batch['img_center'].flatten(0, 1)
    bn = len(image)

    # estimate focal length, and bbox
    bbox_info = self.bbox_est(center, scale, img_focal, img_center)

    # backbone
    feature = self.backbone(image[:,:,:,32:-32])
    feature = feature.float()

    # space-time module
    if self.st_module is not None:
        bb = einops.repeat(bbox_info, 'b c -> b c h w', h=16, w=12)
        feature = torch.cat([feature, bb], dim=1)

        feature = einops.rearrange(feature, '(b t) c h w -> (b h w) t c', t=16)
        feature = self.st_module(feature)
        feature = einops.rearrange(feature, '(b h w) t c -> (b t) c h w', h=16, w=12)

    # smpl_head: transformer + smpl
    # pred_mano_params, pred_cam, pred_mano_params_list = self.mano_head(feature)
    # pred_shape = pred_mano_params_list['pred_shape']
    # pred_pose = pred_mano_params_list['pred_pose']
    pred_pose, pred_shape, pred_cam = self.mano_head(feature)
    pred_rotmat_0 = rot6d_to_rotmat(pred_pose).reshape(-1, self.pose_num, 3, 3)

    # smpl motion module
    if self.motion_module is not None:
        bb = einops.rearrange(bbox_info, '(b t) c -> b t c', t=16)
        pred_pose = einops.rearrange(pred_pose, '(b t) c -> b t c', t=16)
        pred_pose = torch.cat([pred_pose, bb], dim=2)

        pred_pose = self.motion_module(pred_pose)
        pred_pose = einops.rearrange(pred_pose, 'b t c -> (b t) c')

    out = {}
    if 'do_flip' in batch:
        pred_cam[..., 1] *= -1
        center[..., 0] = _INPUT_WIDTH - center[..., 0] - 1
        img_center = img_center.clone()
        img_center[..., 0] = _INPUT_WIDTH - img_center[..., 0] - 1
    out['pred_cam'] = pred_cam
    out['pred_pose'] = pred_pose
    out['pred_shape'] = pred_shape
    out['pred_rotmat'] = rot6d_to_rotmat(out['pred_pose']).reshape(-1, self.pose_num, 3, 3)
    out['pred_rotmat_0'] = pred_rotmat_0

    s_out = self.mano.query(out)
    j3d = s_out.joints
    j2d = self.project(j3d, out['pred_cam'], center, scale, img_focal, img_center)
    j2d = j2d / self.crop_size - 0.5 # norm to [-0.5, 0.5]

    trans_full = self.get_trans(out['pred_cam'], center, scale, img_focal, img_center)
    out['trans_full'] = trans_full

    output = {
        'pred_mano_params': {
            'global_orient': out['pred_rotmat'][:, :1].clone(),
            'hand_pose': out['pred_rotmat'][:, 1:].clone(),
            'betas': out['pred_shape'].clone(),
        },
        'pred_keypoints_3d': j3d.clone(),
        'pred_keypoints_2d': j2d.clone(),
        'out': out,
    }
    # print(output)
    # output['gt_project_j2d'] = self.project(batch['gt_j3d_wo_trans'].clone().flatten(0,1), out['pred_cam'], center, scale, img_focal, img_center)
    # output['gt_project_j2d'] = output['gt_project_j2d'] / self.crop_size - 0.5


    return output
