def hawor_motion_estimation(args, start_idx, end_idx, seq_folder):
    model, model_cfg = _SHARED_MODEL
    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
    model = model.to(device)
    model.eval()

    _, img_folder = resolve_paths(args.video_path)
    imgfiles = np.array(natsorted(glob(f'{img_folder}/*.png')))

    tracks = np.load(f'{seq_folder}/tracks_{start_idx}_{end_idx}/model_tracks.npy', allow_pickle=True).item()
    img_focal = args.img_focal
    if img_focal is None:
        try:
            with open(os.path.join(seq_folder, 'est_focal.txt'), 'r') as file:
                img_focal = file.read()
                img_focal = float(img_focal)
        except:
            img_focal = 600
            print(f'No focal length provided, use default {img_focal}')
            with open(os.path.join(seq_folder, 'est_focal.txt'), 'w') as file:
                file.write(str(img_focal))

    tid = np.array([tr for tr in tracks])

    if os.path.exists(f'{seq_folder}/tracks_{start_idx}_{end_idx}/frame_chunks_all.npy'):
        print("skip hawor motion estimation")
        frame_chunks_all = joblib.load(f'{seq_folder}/tracks_{start_idx}_{end_idx}/frame_chunks_all.npy')
        return frame_chunks_all, img_focal

    print(f'Running hawor on {seq_folder} ...')

    left_trk = []
    right_trk = []
    for k, idx in enumerate(tid):
        trk = tracks[idx]

        valid = np.array([t['det'] for t in trk])
        is_right = np.concatenate([t['det_handedness'] for t in trk])[valid]

        if is_right.sum() / len(is_right) < 0.5:
            left_trk.extend(trk)
        else:
            right_trk.extend(trk)
    left_trk = sorted(left_trk, key=lambda x: x['frame'])
    right_trk = sorted(right_trk, key=lambda x: x['frame'])
    final_tracks = {
        0: left_trk,
        1: right_trk
    }
    tid = [0, 1]

    img = cv2.imread(imgfiles[0])
    img_center = args.calibration_center
    frame_chunks_all = defaultdict(list)
    for idx in tid:
        print(f"tracklet {idx}:")
        trk = final_tracks[idx]

        # interp bboxes
        valid = np.array([t['det'] for t in trk])
        if valid.sum() < 2:
            continue
        boxes = np.concatenate([t['det_box'] for t in trk])
        non_zero_indices = np.where(np.any(boxes != 0, axis=1))[0]
        first_non_zero = non_zero_indices[0]
        last_non_zero = non_zero_indices[-1]
        boxes[first_non_zero:last_non_zero+1] = interpolate_bboxes(boxes[first_non_zero:last_non_zero+1])
        valid[first_non_zero:last_non_zero+1] = True


        boxes = boxes[first_non_zero:last_non_zero+1]
        is_right = np.concatenate([t['det_handedness'] for t in trk])[valid]
        frame = np.array([t['frame'] for t in trk])[valid]

        if is_right.sum() / len(is_right) < 0.5:
            is_right = np.zeros((len(boxes), 1))
        else:
            is_right = np.ones((len(boxes), 1))

        frame_chunks, boxes_chunks = parse_chunks(frame, boxes, min_len=1)
        frame_chunks_all[idx] = frame_chunks

        if len(frame_chunks) == 0:
            continue

        for frame_ck, boxes_ck in zip(frame_chunks, boxes_chunks):
            print(f"inference from frame {frame_ck[0]} to {frame_ck[-1]}")
            img_ck = imgfiles[frame_ck]
            if is_right[0] > 0:
                do_flip = False
            else:
                do_flip = True

            results = model.inference(img_ck, boxes_ck, img_focal=img_focal, img_center=([img.shape[1]-1-img_center[0], img_center[1]] if do_flip else img_center), do_flip=do_flip)

            data_out = {
                "init_root_orient": results["pred_rotmat"][None, :, 0], # (B, T, 3, 3)
                "init_hand_pose": results["pred_rotmat"][None, :, 1:], # (B, T, 15, 3, 3)
                "init_trans": results["pred_trans"][None, :, 0],  # (B, T, 3)
                "init_betas": results["pred_shape"][None, :]  # (B, T, 10)
            }

            # flip left hand
            init_root = rotation_matrix_to_angle_axis(data_out["init_root_orient"])
            init_hand_pose = rotation_matrix_to_angle_axis(data_out["init_hand_pose"])
            if do_flip:
                init_root[..., 1] *= -1
                init_root[..., 2] *= -1
                init_hand_pose[..., 1] *= -1
                init_hand_pose[..., 2] *= -1
            data_out["init_root_orient"] = angle_axis_to_rotation_matrix(init_root)
            data_out["init_hand_pose"] = angle_axis_to_rotation_matrix(init_hand_pose)

            # save camera-space results
            pred_dict={
                k:v.tolist() for k, v in data_out.items()
            }
            pred_path = os.path.join(seq_folder, 'cam_space', str(idx), f"{frame_ck[0]}_{frame_ck[-1]}.json")
            if not os.path.exists(os.path.join(seq_folder, 'cam_space', str(idx))):
                os.makedirs(os.path.join(seq_folder, 'cam_space', str(idx)))
            with open(pred_path, "w") as f:
                json.dump(pred_dict, f, indent=1)


    joblib.dump(frame_chunks_all, f'{seq_folder}/tracks_{start_idx}_{end_idx}/frame_chunks_all.npy')
    return frame_chunks_all, img_focal
